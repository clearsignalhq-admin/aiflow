"""Import a LangGraph project into an AiFlow workflow (Task 57).

The code is only *parsed*, never imported or executed: it is untrusted input. Two paths:

* **Exact**: the files include ``workflow.json`` from an AiFlow export, which is restored as is.
* **Inferred**: the ``StateGraph`` builder calls (``add_node``, ``add_edge``, ``add_conditional_edges``,
  ``set_entry_point``, ``set_finish_point``, ``add_sequence``) give the graph. Each step's type is guessed from
  what its function does (call an LLM, an HTTP client, a database, a retriever, ``interrupt``...) and
  settings that are plain literals (prompt, model, url, SQL) are carried over. Decisions become CONDITION
  steps; a router function that is a simple chain of ``if``/``return`` on ``state[...]`` is translated into an
  expression, anything more complex is left blank for the user to fill in. Everything guessed is reported.
"""
import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.workflow import MAX_EDGES, MAX_NODES, NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.services import expressions

MAX_FILES = 20
MAX_FILE_CHARS = 200_000
MAX_TOTAL_CHARS = 500_000

_START, _END = "__start__", "__end__"
_GRAPH_CLASSES = {"StateGraph", "MessageGraph"}
_METHODS = {"add_node", "add_edge", "add_conditional_edges", "set_entry_point", "set_finish_point", "add_sequence", "set_conditional_entry_point"}

_DB_HINTS = {"execute", "executemany", "cursor", "session", "sqlalchemy", "psycopg2", "psycopg", "sqlite3", "asyncpg", "pymongo", "create_engine"}
_RAG_HINTS = ("retriever", "vectorstore", "vector_store", "similarity_search", "faiss", "chroma", "pinecone", "qdrant", "weaviate", "embed")
_API_HINTS = {"requests", "httpx", "aiohttp", "urlopen", "urllib", "urllib3"}
_TOOL_HINTS = {"tool", "tools", "toolnode", "tool_node", "bind_tools"}
_LLM_HINTS = ("llm", "chat", "openai", "anthropic", "gemini", "chain", "prompt")
_SQL = re.compile(r"^\s*(select|insert|update|delete|with|merge|upsert|create|alter|drop)\b", re.I)
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head"}


@dataclass
class ImportResult:
    workflow: Optional[Workflow] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode: str = "inferred"          # "exact" when restored from workflow.json


# ═══════════════════════════ Entry point ═══════════════════════════

def import_langgraph(files: dict[str, str]) -> ImportResult:
    if not files:
        return ImportResult(errors=["Add at least one Python file."])
    if len(files) > MAX_FILES:
        return ImportResult(errors=[f"Too many files ({len(files)}); the limit is {MAX_FILES}."])
    if any(len(t) > MAX_FILE_CHARS for t in files.values()) or sum(len(t) for t in files.values()) > MAX_TOTAL_CHARS:
        return ImportResult(errors=[f"The files are too large (max {MAX_FILE_CHARS // 1000} KB each, {MAX_TOTAL_CHARS // 1000} KB in total)."])

    exact = _exact(files)
    if exact is not None:
        return exact
    return _Importer(files).run()


def _exact(files: dict[str, str]) -> Optional[ImportResult]:
    """An AiFlow export carries the workflow itself; use it rather than guessing from the code."""
    for path, text in files.items():
        if path.replace("\\", "/").split("/")[-1] != "workflow.json":
            continue
        try:
            workflow = Workflow.model_validate(json.loads(text))
        except (ValueError, TypeError):
            return None                     # not (or no longer) a valid workflow: fall back to reading the code
        if not workflow.nodes:
            return None
        return ImportResult(
            workflow=workflow, mode="exact",
            warnings=["This is an AiFlow export, so the workflow was restored exactly from workflow.json (the Python code was not read)."],
        )
    return None


# ═══════════════════════════ Reading the code ═══════════════════════════

def _name_of(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _humanise(identifier: str) -> str:
    text = re.sub(r"[_\-]+", " ", identifier).strip()
    return (text[:1].upper() + text[1:]) if text else identifier


class _Importer:
    def __init__(self, files: dict[str, str]):
        self.files = files
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.trees: list[tuple[str, ast.Module]] = []
        self.consts: dict[str, str] = {}
        self.funcs: dict[str, ast.AST] = {}
        self.graph_vars: set[str] = set()
        self.branch_tables: dict[str, dict[str, str]] = {}      # NAME = [("label", "step"), ...] at module level
        # collected structure
        self.node_fns: dict[str, Optional[ast.AST]] = {}      # step name → its function definition (or None)
        self.node_order: list[str] = []
        self.edges: list[tuple[str, str, Optional[str]]] = []  # (source, target, label)
        self.decisions: list[tuple[str, Optional[ast.AST], dict[str, str]]] = []  # (source, router fn, label → target)
        self.unresolved = 0
        self.end_steps: set[str] = set()                         # do-nothing steps that only lead to END: they are the END

    # ── driver ──────────────────────────────────────────────────────────────
    def run(self) -> ImportResult:
        self._parse()
        if self.errors and not self.trees:
            return ImportResult(errors=self.errors)
        self._index()
        calls = self._graph_calls()
        if not calls:
            return ImportResult(errors=self.errors + ["No LangGraph StateGraph was found. Upload the file that builds the graph (it calls StateGraph(...), add_node(...) and add_edge(...))."])
        for _, _, call in calls:
            self._apply(call)
        return self._build()

    def _parse(self) -> None:
        for path, text in self.files.items():
            if not path.endswith(".py"):
                continue
            try:
                self.trees.append((path, ast.parse(text, filename=path)))
            except SyntaxError as exc:
                self.errors.append(f"{path}: line {exc.lineno}: {exc.msg}")
            except (RecursionError, MemoryError, ValueError):
                self.errors.append(f"{path}: the file is too deeply nested or contains invalid characters.")

    def _index(self) -> None:
        for _, tree in self.trees:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs.setdefault(node.name, node)
                elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.consts.setdefault(target.id, node.value.value)
                elif isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
                    table = self._branch_table(node.value)
                    if table:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                self.branch_tables.setdefault(target.id, table)

    # ── finding the builder calls ───────────────────────────────────────────
    def _is_graph_root(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            return _name_of(node.func) in _GRAPH_CLASSES or (
                isinstance(node.func, ast.Attribute) and node.func.attr in _METHODS and self._is_graph_receiver(node.func.value)
            )
        return False

    def _is_graph_receiver(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in self.graph_vars) or self._is_graph_root(node)

    def _graph_calls(self) -> list[tuple[int, tuple[int, int], ast.Call]]:
        # variables that hold a graph (``builder = StateGraph(State)``), possibly after a chain of builder calls
        for _, tree in self.trees:
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and self._is_graph_root(node.value):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    self.graph_vars.update(t.id for t in targets if isinstance(t, ast.Name))
        found: list[tuple[int, tuple[int, int], ast.Call]] = []
        for index, (_, tree) in enumerate(self.trees):
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _METHODS
                        and self._is_graph_receiver(node.func.value)):
                    found.append((index, (node.lineno, node.col_offset), node))
        found.sort(key=lambda item: (item[0], item[1]))
        return found

    # ── reading arguments ───────────────────────────────────────────────────
    def _endpoint(self, node: Optional[ast.AST]) -> Optional[str]:
        """The step name an argument refers to: a string, a named constant, START/END, or a function's name."""
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {"__start__": _START, "__end__": _END}.get(node.value, node.value)
        if isinstance(node, ast.Name):
            if node.id == "START":
                return _START
            if node.id == "END":
                return _END
            return self.consts.get(node.id)
        return None

    def _endpoints(self, node: Optional[ast.AST]) -> list[str]:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [e for e in (self._endpoint(x) for x in node.elts) if e]
        single = self._endpoint(node)
        return [single] if single else []

    def _add_node(self, name: str, fn: Optional[ast.AST]) -> None:
        if name in (_START, _END):
            return
        if name not in self.node_fns:
            self.node_order.append(name)
        if fn is not None or name not in self.node_fns:
            self.node_fns[name] = fn

    def _function_of(self, node: Optional[ast.AST]) -> Optional[ast.AST]:
        if isinstance(node, (ast.Name, ast.Attribute)):
            return self.funcs.get(_name_of(node) or "")
        if isinstance(node, ast.Call):                              # functools.partial(fn, ...), ToolNode(...), create_react_agent(...)
            callee = _name_of(node.func) or ""
            if callee == "partial" and node.args:
                return self._function_of(node.args[0])
            return node
        return node if isinstance(node, ast.Lambda) else None

    def _apply(self, call: ast.Call) -> None:
        method = call.func.attr                                       # type: ignore[union-attr]
        args = call.args
        kwargs = {k.arg: k.value for k in call.keywords if k.arg}
        if method == "add_node":
            if len(args) >= 2 or "node" in kwargs or "action" in kwargs:
                name = self._endpoint(args[0] if args else kwargs.get("node"))
                fn_node = args[1] if len(args) > 1 else kwargs.get("action")
            else:                                                     # add_node(fn): the step is named after the function
                fn_node = args[0] if args else None
                name = _name_of(fn_node) if isinstance(fn_node, (ast.Name, ast.Attribute)) else None
            if name:
                self._add_node(name, self._function_of(fn_node))
            else:
                self.unresolved += 1
        elif method == "add_edge":
            starts = self._endpoints(args[0] if args else kwargs.get("start_key"))
            ends = self._endpoints(args[1] if len(args) > 1 else kwargs.get("end_key"))
            if not starts or not ends:
                self.unresolved += 1
            for a in starts:
                for b in ends:
                    self.edges.append((a, b, None))
        elif method == "set_entry_point":
            for b in self._endpoints(args[0] if args else kwargs.get("key")):
                self.edges.append((_START, b, None))
        elif method == "set_finish_point":
            for a in self._endpoints(args[0] if args else kwargs.get("key")):
                self.edges.append((a, _END, None))
        elif method == "add_sequence":
            names: list[str] = []
            seq = args[0] if args else kwargs.get("nodes")
            for item in (seq.elts if isinstance(seq, (ast.List, ast.Tuple)) else []):
                if isinstance(item, ast.Tuple) and len(item.elts) == 2:
                    name = self._endpoint(item.elts[0])
                    if name:
                        self._add_node(name, self._function_of(item.elts[1]))
                        names.append(name)
                else:
                    name = _name_of(item)
                    if name:
                        self._add_node(name, self._function_of(item))
                        names.append(name)
            self.edges += [(a, b, None) for a, b in zip(names, names[1:])]
        elif method == "add_conditional_edges":
            source = self._endpoint(args[0] if args else kwargs.get("source"))
            router = args[1] if len(args) > 1 else kwargs.get("path")
            path_map = args[2] if len(args) > 2 else kwargs.get("path_map")
            if not source:
                self.unresolved += 1
                return
            self.decisions.append((source, self._function_of(router), self._path_map(path_map, router)))
        else:
            self.warnings.append(f"{method} is not supported and was ignored.")

    def _path_map(self, node: Optional[ast.AST], router: Optional[ast.AST]) -> dict[str, str]:
        """label → target step. Without an explicit map, the router's returned step names are both label and target."""
        if isinstance(node, ast.Dict):
            out: dict[str, str] = {}
            for k, v in zip(node.keys, node.values):
                label = self._endpoint(k) if k is not None else None
                if label is None and isinstance(k, ast.Constant):
                    label = str(k.value).lower() if isinstance(k.value, bool) else str(k.value)
                target = self._endpoint(v)
                if label is not None and target:
                    out[label] = target
            return out
        if isinstance(node, (ast.List, ast.Tuple)):
            return {t: t for t in (self._endpoint(x) for x in node.elts) if t}
        fn = self._function_of(router)
        return self._table_from_router(fn) or ({t: t for t in self._returned_names(fn)} if fn is not None else {})

    @staticmethod
    def _branch_table(node: ast.AST) -> dict[str, str]:
        """``[("label", "step"), ...]`` → {label: step}; entries without a string label are skipped."""
        table: dict[str, str] = {}
        for item in getattr(node, "elts", []):
            if (isinstance(item, ast.Tuple) and len(item.elts) == 2 and all(isinstance(e, ast.Constant) for e in item.elts)
                    and isinstance(item.elts[0].value, str) and isinstance(item.elts[1].value, str)):
                table[item.elts[0].value] = item.elts[1].value
        return table

    def _literal_returns(self, expr: Optional[ast.AST]) -> list[str]:
        """Step names a ``return`` can produce *directly* (a string, END, a named constant, either side of a conditional)."""
        if expr is None:
            return []
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return [{"__end__": _END}.get(expr.value, expr.value)]
        if isinstance(expr, ast.Name):
            if expr.id == "END":
                return [_END]
            return [self.consts[expr.id]] if expr.id in self.consts else []
        if isinstance(expr, ast.IfExp):
            return self._literal_returns(expr.body) + self._literal_returns(expr.orelse)
        if isinstance(expr, (ast.List, ast.Tuple)):
            return [n for e in expr.elts for n in self._literal_returns(e)]
        return []

    def _returned_names(self, fn: Optional[ast.AST]) -> list[str]:
        names: list[str] = []
        for node in ast.walk(fn) if fn is not None else []:
            if isinstance(node, ast.Return):
                for value in self._literal_returns(node.value):
                    if value not in names:
                        names.append(value)
        return names

    def _table_from_router(self, fn: Optional[ast.AST]) -> dict[str, str]:
        """AiFlow's own routers delegate to ``choose_branches(step_id, BRANCHES, data)``; read BRANCHES."""
        for node in ast.walk(fn) if fn is not None else []:
            if isinstance(node, ast.Call) and _name_of(node.func) == "choose_branches" and len(node.args) >= 2:
                second = node.args[1]
                if isinstance(second, ast.Name) and second.id in self.branch_tables:
                    return dict(self.branch_tables[second.id])
        return {}

    # ── assembling the workflow ─────────────────────────────────────────────
    def _fold_entry_and_exit(self) -> None:
        """AiFlow's own exports express START and END as do-nothing steps (``start``, ``end``, ``end-safe``...). Read the
        entry step as the graph's START, and each exit step as an END node, instead of importing pointless TRANSFORM steps."""
        decision_sources = {src for src, _, _ in self.decisions}       # a step a decision hangs off must stay
        for name in list(self.node_order):
            if name in decision_sources or not self._is_passthrough(self.node_fns.get(name)):
                continue
            incoming = [e for e in self.edges if e[1] == name]
            outgoing = [e for e in self.edges if e[0] == name]
            lowered = name.lower()
            if lowered in {"start", "begin", "entry"} and incoming and all(e[0] == _START for e in incoming):
                self.edges = [e for e in self.edges if e not in incoming and e not in outgoing] + [(_START, e[1], e[2]) for e in outgoing]
                self.node_order.remove(name)
                self.node_fns.pop(name, None)
            elif re.match(r"(end|finish|done|exit|stop)\b|(end|finish|done|exit|stop)[_\-]", lowered) and outgoing and all(e[1] == _END for e in outgoing):
                self.edges = [e for e in self.edges if e not in outgoing]
                self.end_steps.add(name)

    def _build(self) -> ImportResult:
        self._fold_entry_and_exit()
        nodes: dict[str, WorkflowNode] = {}
        guessed: list[str] = []
        used_ids: set[str] = {_START, _END}

        def ensure(name: str) -> None:
            if name in (_START, _END) or name in nodes:
                return
            fn = self.node_fns.get(name)
            if name in self.end_steps:
                nodes[name] = WorkflowNode(id=name[:100], type=NodeType.END, name=_humanise(name)[:200], config={})
                return
            kind, config = self._classify(fn)
            if name not in self.node_fns:
                self.warnings.append(f"Step '{name}' is used in an edge but never added with add_node; it was created empty.")
            if fn is not None and kind == NodeType.TRANSFORM and not isinstance(fn, ast.Lambda) and not config:
                guessed.append(name)
            elif fn is not None and kind != NodeType.TRANSFORM:
                guessed.append(f"{name} ({kind.value})")
            nodes[name] = WorkflowNode(id=name[:100], type=kind, name=_humanise(name)[:200], config=config)

        for name in self.node_order:
            ensure(name)
        for a, b, _ in self.edges:
            ensure(a)
            ensure(b)
        for source, _, mapping in self.decisions:
            ensure(source)
            for target in mapping.values():
                ensure(target)

        # Decisions become CONDITION steps.
        edges: list[tuple[str, str, Optional[str]]] = list(self.edges)
        for source, router, mapping in self.decisions:
            src_fn = self.node_fns.get(source)
            label_expr = self._translate_router(router)
            if source in nodes and self._is_trivial(src_fn) and nodes[source].type == NodeType.TRANSFORM:
                condition = nodes[source]                               # a pass-through step that only exists to route
                condition.type = NodeType.CONDITION
            else:
                rid = self._unique(f"route_{source}", nodes)
                condition = WorkflowNode(id=rid[:100], type=NodeType.CONDITION, name=f"Route after {_humanise(source)}"[:200], config={})
                nodes[rid] = condition
                if source == _START:
                    edges.append((_START, rid, None))
                else:
                    edges.append((source, rid, None))
            condition.config = {"expression": label_expr} if label_expr else {}
            if not label_expr:
                self.warnings.append(
                    f"The decision after '{source}' uses a Python function that could not be turned into an expression. "
                    f"Open the step “{condition.name}” and write the rule that returns {', '.join(sorted(mapping)) or 'the branch labels'}."
                )
            if not mapping:
                self.warnings.append(f"The branches of the decision after '{source}' could not be read from the code.")
            cid = next(k for k, v in nodes.items() if v is condition)
            for label, target in mapping.items():
                edges.append((cid, target, label))

        return self._assemble(nodes, edges, guessed, used_ids)

    @staticmethod
    def _unique(base: str, nodes: dict[str, WorkflowNode]) -> str:
        candidate, i = base, 2
        while candidate in nodes:
            candidate, i = f"{base}_{i}", i + 1
        return candidate

    def _assemble(self, nodes: dict[str, WorkflowNode], edges: list[tuple[str, str, Optional[str]]],
                  guessed: list[str], used_ids: set[str]) -> ImportResult:
        def free(base: str) -> str:
            candidate, i = base, 2
            while candidate in nodes or candidate in {n.id for n in nodes.values()}:
                candidate, i = f"{base}_{i}", i + 1
            return candidate

        start_id, end_id = free("start"), free("end")
        id_of = {name: n.id for name, n in nodes.items()}
        id_of[_START], id_of[_END] = start_id, end_id

        out: list[WorkflowEdge] = []
        seen: set[tuple[str, str, Optional[str]]] = set()
        for a, b, label in edges:
            key = (id_of.get(a, a), id_of.get(b, b), label)
            if key in seen or key[0] == end_id:
                continue
            seen.add(key)
            out.append(WorkflowEdge(source=key[0], target=key[1], condition=label))

        has_in = {e.target for e in out}
        has_out = {e.source for e in out}
        ordered = [n for n in nodes.values()]
        if not any(e.source == start_id for e in out):
            roots = [n for n in ordered if n.id not in has_in]
            if roots:
                self.warnings.append("The graph has no entry point (set_entry_point or an edge from START), so START was connected to: "
                                     + ", ".join(n.name for n in roots[:5]) + ".")
            for n in roots:
                out.append(WorkflowEdge(source=start_id, target=n.id))
        has_end_step = any(n.type == NodeType.END for n in ordered)
        if not any(e.target == end_id for e in out) and not has_end_step:
            leaves = [n for n in ordered if n.id not in has_out]
            self.warnings.append("No step leads to END, so the steps with no outgoing edge were connected to END.")
            for n in leaves:
                out.append(WorkflowEdge(source=n.id, target=end_id))

        all_nodes = [WorkflowNode(id=start_id, type=NodeType.START, name="Start", config={})] + ordered
        if any(e.target == end_id for e in out):
            all_nodes.append(WorkflowNode(id=end_id, type=NodeType.END, name="End", config={}))
        if len(all_nodes) > MAX_NODES or len(out) > MAX_EDGES:
            return ImportResult(errors=self.errors + [f"The graph is too large to import (max {MAX_NODES} steps and {MAX_EDGES} edges)."])

        if guessed:
            self.warnings.append(
                "Step types were inferred from the code and may need correcting: " + ", ".join(guessed[:8]) + ("…" if len(guessed) > 8 else "") + "."
            )
        if self.unresolved:
            self.warnings.append(f"{self.unresolved} call(s) used step names that are computed at run time and could not be read.")
        self.warnings.append("Step settings were carried over only where they are plain literals in the code (prompt, model, URL, SQL). Review each step, then run Validate.")
        try:
            workflow = Workflow(name="Imported LangGraph workflow", description=self._module_doc(), nodes=all_nodes, edges=out)
        except ValueError as exc:
            return ImportResult(errors=self.errors + [f"The graph could not be converted: {exc}"])
        skipped = [f"Skipped {e}" for e in self.errors]       # a file that does not parse should not block the rest
        return ImportResult(workflow=workflow, warnings=skipped + self.warnings)

    def _module_doc(self) -> str:
        for _, tree in self.trees:
            doc = ast.get_docstring(tree)
            if doc:
                return re.sub(r"\s+", " ", doc).strip()[:300]
        return ""

    # ── classifying a step ──────────────────────────────────────────────────
    @staticmethod
    def _is_trivial(fn: Optional[ast.AST]) -> bool:
        """No calls at all: the function only returns a literal, so it exists just to anchor a decision."""
        if fn is None:
            return True
        if isinstance(fn, ast.Lambda):
            return not any(isinstance(n, ast.Call) for n in ast.walk(fn.body))
        return isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not any(isinstance(n, ast.Call) for n in ast.walk(fn))

    @staticmethod
    def _is_passthrough(fn: Optional[ast.AST]) -> bool:
        """Like _is_trivial, but tolerates ``state.get(...)`` / ``dict(...)``: the step only shuffles data."""
        if fn is None:
            return True
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        allowed = {"get", "dict", "list", "copy", "len"}
        return all(_name_of(n.func) in allowed for n in ast.walk(fn) if isinstance(n, ast.Call))

    def _classify(self, fn: Optional[ast.AST]) -> tuple[NodeType, dict[str, Any]]:
        if fn is None or isinstance(fn, ast.Lambda):
            return NodeType.TRANSFORM, {}
        idents: set[str] = set()
        called: list[str] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                idents.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                idents.add(node.attr.lower())
            elif isinstance(node, ast.Call):
                name = _name_of(node.func)
                if name:
                    called.append(name.lower())
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            idents |= {(_name_of(d.func) if isinstance(d, ast.Call) else _name_of(d) or "").lower() for d in fn.decorator_list}
        every = idents | set(called)

        def has(words: set[str]) -> bool:
            return bool(every & words)

        def has_part(parts: tuple[str, ...]) -> bool:
            return any(p in w for w in every for p in parts)

        if "interrupt" in every or "input" in called:
            return NodeType.HITL, self._hitl_config(fn)
        if any(w.startswith("database_") for w in every) or has(_DB_HINTS):
            return NodeType.DATABASE, self._db_config(fn)
        if any(w.startswith("rag_") for w in every) or has_part(_RAG_HINTS):
            return NodeType.RAG, self._rag_config(fn)
        if any(w.startswith("api_") for w in every) or has(_API_HINTS):
            return NodeType.API, self._api_config(fn)
        if any(w.startswith("tool_") for w in every) or has(_TOOL_HINTS):
            return NodeType.TOOL, {"name": getattr(fn, "name", ""), **({"description": ast.get_docstring(fn)[:200]} if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(fn) else {})}
        if has_part(_LLM_HINTS):
            return NodeType.LLM, self._llm_config(fn)
        config: dict[str, Any] = {}
        doc = ast.get_docstring(fn) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        if doc:
            config["description"] = re.sub(r"\s+", " ", doc).strip()[:200]
        return NodeType.TRANSFORM, config

    @staticmethod
    def _strings(fn: ast.AST) -> list[str]:
        return [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def _llm_config(self, fn: ast.AST) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in ("model", "model_name") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        config["model"] = kw.value.value
                    if kw.arg == "temperature" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                        config["temperature"] = kw.value.value
        prompts = [s for s in self._strings(fn) if len(s) >= 20 and " " in s and not s.lower().startswith(("http", "select "))]
        system = next((s for s in prompts if re.search(r"\b(you are|your task|respond|answer|classify|summari[sz]e)\b", s, re.I)), None)
        chosen = system or (max(prompts, key=len) if prompts else None)
        if chosen:
            config["prompt"] = chosen[:2000]
        return config

    def _api_config(self, fn: ast.AST) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _HTTP_METHODS:
                config.setdefault("method", node.func.attr.upper())
        url = next((s for s in self._strings(fn) if re.match(r"https?://", s)), None)
        if url:
            config["url"] = url
        return config

    def _db_config(self, fn: ast.AST) -> dict[str, Any]:
        query = next((s for s in self._strings(fn) if _SQL.match(s)), None)
        return {"query": query[:2000], "connection": "env:DB_URL"} if query else {"connection": "env:DB_URL"}

    def _rag_config(self, fn: ast.AST) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in ("k", "top_k") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                        config["topK"] = kw.value.value
                    if kw.arg in ("collection_name", "index_name", "namespace") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        config["knowledgeBase"] = kw.value.value
        return config

    def _hitl_config(self, fn: ast.AST) -> dict[str, Any]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and _name_of(node.func) == "interrupt" and node.args:
                payload = node.args[0]
                if isinstance(payload, ast.Dict):
                    for k, v in zip(payload.keys, payload.values):
                        if isinstance(k, ast.Constant) and k.value in ("instructions", "question", "message") and isinstance(v, ast.Constant) and isinstance(v.value, str):
                            return {"instructions": v.value[:500]}
                if isinstance(payload, ast.Constant) and isinstance(payload.value, str):
                    return {"instructions": payload.value[:500]}
        return {}

    # ── routers → expressions ───────────────────────────────────────────────
    def _translate_router(self, fn: Optional[ast.AST]) -> Optional[str]:
        """Turn ``if/return`` router functions into an AiFlow expression, or None when they are not that simple."""
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return None
        body = [fn.body] if isinstance(fn, ast.Lambda) else list(fn.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]                                           # docstring
        arg = fn.args.args[0].arg if fn.args.args else "state"
        try:
            expr = self._statements_to_expr(body, arg)
        except _Untranslatable:
            return None
        if expr is None:
            return None
        text = ast.unparse(expr)
        return text if len(text) <= 400 and expressions.check_syntax(text) is None else None

    def _statements_to_expr(self, body: list, state: str) -> Optional[ast.expr]:
        """``if c: return a`` followed by ``return b``  →  ``a if c else b`` (code that falls through continues below the ``if``)."""
        try:
            return self._sequence(list(body), state)
        except RecursionError:
            raise _Untranslatable

    def _sequence(self, stmts: list, state: str) -> ast.expr:
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    raise _Untranslatable
                return self._expr(stmt.value, state)
            if isinstance(stmt, ast.If):
                rest = stmts[i + 1:]
                return ast.IfExp(
                    test=self._expr(stmt.test, state),
                    body=self._sequence(list(stmt.body) + rest, state),
                    orelse=self._sequence(list(stmt.orelse) + rest, state),
                )
            raise _Untranslatable                                    # assignments, loops, calls... are not translated
        raise _Untranslatable                                        # ran off the end without returning

    def _expr(self, node: ast.expr, state: str) -> ast.expr:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                node = ast.Constant(value={"__end__": "__end__"}.get(node.value, node.value))
            return node
        if isinstance(node, ast.Name):
            if node.id == "END":
                return ast.Constant(value=_END)
            if node.id in self.consts:
                return ast.Constant(value=self.consts[node.id])
            if node.id in ("True", "False", "None"):
                return node
            raise _Untranslatable
        field_name = self._state_field(node, state)
        if field_name is not None:
            return field_name
        if isinstance(node, ast.IfExp):
            return ast.IfExp(test=self._expr(node.test, state), body=self._expr(node.body, state), orelse=self._expr(node.orelse, state))
        if isinstance(node, ast.BoolOp):
            return ast.BoolOp(op=node.op, values=[self._expr(v, state) for v in node.values])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return ast.UnaryOp(op=node.op, operand=self._expr(node.operand, state))
        if isinstance(node, ast.Compare) and all(isinstance(op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)) for op in node.ops):
            return ast.Compare(left=self._expr(node.left, state), ops=node.ops, comparators=[self._expr(c, state) for c in node.comparators])
        if isinstance(node, (ast.List, ast.Tuple)):
            return ast.List(elts=[self._expr(e, state) for e in node.elts], ctx=ast.Load())
        raise _Untranslatable

    def _state_field(self, node: ast.expr, state: str) -> Optional[ast.expr]:
        """``state["x"]``, ``state.get("x")``, ``state.get("x", d)``, ``state.x`` → ``input.x`` (nested access too)."""
        if isinstance(node, ast.Subscript):
            inner = self._state_field(node.value, state) if not (isinstance(node.value, ast.Name) and node.value.id == state) else ast.Name(id="input", ctx=ast.Load())
            if inner is None or not (isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                return None
            return self._field(inner, node.slice.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            base = ast.Name(id="input", ctx=ast.Load()) if (isinstance(node.func.value, ast.Name) and node.func.value.id == state) else self._state_field(node.func.value, state)
            if base is None or not (isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                return None
            return self._field(base, node.args[0].value)
        if isinstance(node, ast.Attribute):
            base = ast.Name(id="input", ctx=ast.Load()) if (isinstance(node.value, ast.Name) and node.value.id == state) else self._state_field(node.value, state)
            return self._field(base, node.attr) if base is not None else None
        return None

    @staticmethod
    def _field(base: ast.expr, name: str) -> ast.expr:
        if name.isidentifier() and not name.startswith("_"):
            return ast.Attribute(value=base, attr=name, ctx=ast.Load())
        return ast.Subscript(value=base, slice=ast.Constant(value=name), ctx=ast.Load())


class _Untranslatable(Exception):
    pass

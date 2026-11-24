"""LangGraph exporter: turns a Workflow into a runnable Python project.

The AiFlow workflow stays the source of truth: it is shipped as ``workflow.json`` and every step reads
its settings from there. Generated Python contains only identifiers derived from node ids, never the
text of prompts, URLs, queries or names, so user-authored text cannot become code.

Project layout (all paths relative to the project folder):

    workflow.json            the workflow as designed
    state.py                 graph state with reducers (parallel branches merge safely)
    nodes.py                 one function per step
    integrations.py          stubs for TOOL / API / DATABASE / RAG / TRANSFORM (return fixtures; TODOs)
    routing.py               one router per decision step
    graph.py                 builds the StateGraph
    runtime.py               rendering, LLM call, mock fixtures, branch selection
    aiflow_expressions.py    the safe expression evaluator used by the AiFlow simulator (copied)
    aiflow_schema.py         schema helpers used for mock data (copied)
    main.py                  command-line runner (handles human-review pauses)
    tests/                   a smoke test and, if a suite is supplied, one test per suite case
    README.md, requirements.txt, .env.example, pytest.ini

Differences from the simulator are listed in the generated README and in ``DIFFERENCES`` below.
"""
import inspect
import io
import json
import keyword
import pprint
import re
import zipfile
from collections import deque
from typing import Any, Optional

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.services import assertions as assertions_module
from app.services import expressions as expressions_module
from app.services import langgraph_connectors as connectors_module
from app.services import langgraph_templates as tpl
from app.services import schema_utils as schema_module
from app.services.linter import _is_irreversible

DIFFERENCES = [
    "State accumulates: each step's output is merged into the running data, so later steps can use earlier results. "
    "The simulator passes only the previous step's output.",
    "When a decision matches no branch the generated code raises RoutingError; the simulator explores every branch.",
    "Steps with several outgoing edges run those branches in parallel. If separate parallel branches rejoin, "
    "the joining step runs once per arriving branch.",
    "API, DATABASE and RAG steps make real requests, queries and searches (connectors.py); TOOL and TRANSFORM steps raise "
    "NotImplementedError until you implement them in integrations.py. AIFLOW_MOCK=1 returns fixtures for all of them.",
]

TARGET_SUFFIX = {"langgraph": "langgraph", "python": "python"}
PLAIN_DIFFERENCES = [
    "State accumulates: each step's output is merged into the running data, so later steps can use earlier results. "
    "The simulator passes only the previous step's output.",
    "Each step runs at most once per run (like the simulator): a step several branches lead into runs once, and loops are not repeated.",
    "When a decision matches no branch the generated code raises RoutingError; the simulator explores every branch.",
    "A human review asks synchronously (in the terminal, or through the on_review callback you pass to engine.run); "
    "a run cannot be paused in one process and resumed in another.",
    "API, DATABASE and RAG steps make real requests, queries and searches (connectors.py); TOOL and TRANSFORM steps raise "
    "NotImplementedError until you implement them in integrations.py. AIFLOW_MOCK=1 returns fixtures for all of them.",
]

_RESERVED_GRAPH_NAMES = {"data", "visited", "result"}   # LangGraph rejects a step named like a state key
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)    # fixed so the same workflow always produces the same bytes


class ExportError(ValueError):
    """The workflow cannot be exported (for example it has no START node)."""


# ── Naming ───────────────────────────────────────────────────────────────────

def _slug(text: str, fallback: str = "step") -> str:
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if not base:
        base = fallback
    if base[0].isdigit():
        base = f"{fallback}_{base}"
    return base


def _unique(base: str, used: set[str]) -> str:
    """A step name that is a valid identifier, not a state key or keyword, and not used yet."""
    name = f"{base}_step" if base in _RESERVED_GRAPH_NAMES or keyword.iskeyword(base) else base
    candidate, i = name, 2
    while candidate in used:
        candidate = f"{name}_{i}"
        i += 1
    used.add(candidate)
    return candidate


def _safe_text(text: Any, limit: int = 100) -> str:
    """One line of plain text that is safe inside a comment or docstring."""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    value = value.replace("\\", "/").replace('"', "'")
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _literal(value: Any) -> str:
    return pprint.pformat(value, width=96, sort_dicts=False)


def _project_slug(name: str) -> str:
    return _slug(name, "workflow").replace("_", "-") or "workflow"


# ── The exporter ─────────────────────────────────────────────────────────────

class LangGraphExporter:
    """Exports a workflow as a runnable Python project: ``target="langgraph"`` (default) or ``"python"`` (no framework)."""

    def export(
        self,
        workflow: Workflow,
        cases: Optional[list[dict[str, Any]]] = None,
        run_seed: int = 0,
        target: str = "langgraph",
    ) -> dict[str, str]:
        """Return the project as ``{relative path: file text}``."""
        if target not in TARGET_SUFFIX:
            raise ExportError(f"Unknown export target {target!r}.")
        plain = target == "python"
        plan = _Plan(workflow, target)
        files: dict[str, str] = {
            "workflow.json": json.dumps(workflow.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            "state.py": tpl.STATE_PLAIN_PY if plain else tpl.STATE_PY,
            "runtime.py": tpl.RUNTIME_PY,
            "aiflow_expressions.py": inspect.getsource(expressions_module),
            "aiflow_schema.py": inspect.getsource(schema_module),
            "nodes.py": plan.nodes_py(),
            "integrations.py": plan.integrations_py(),
            "routing.py": plan.routing_py(),
            "graph.py": plan.graph_py(),
            "main.py": tpl.MAIN_PLAIN_PY if plain else tpl.MAIN_PY,
            "requirements.txt": plan.requirements(),
            ".env.example": plan.env_example(),
            "pytest.ini": tpl.PYTEST_INI,
            "README.md": plan.readme(has_cases=bool(cases)),
            "tests/aiflow_assertions.py": _assertions_source(),
            "tests/cases.json": json.dumps(_cases_json(cases or []), indent=2, ensure_ascii=False) + "\n",
            "tests/test_workflow.py": (tpl.TEST_PLAIN_PY if plain else tpl.TEST_PY).replace("__RUN_SEED__", str(int(run_seed))),
        }
        if plain:
            files["review.py"] = tpl.REVIEW_PY
            files["engine.py"] = tpl.ENGINE_PY
        if plan.uses_connectors:
            files["connectors.py"] = connectors_module.CONNECTORS_PY
        return files

    def export_zip(
        self,
        workflow: Workflow,
        cases: Optional[list[dict[str, Any]]] = None,
        run_seed: int = 0,
        target: str = "langgraph",
    ) -> tuple[str, bytes]:
        """Return ``(project folder name, zip bytes)``. Deterministic: the same input gives identical bytes."""
        files = self.export(workflow, cases, run_seed, target)
        return zip_project(f"{_project_slug(workflow.name)}-{TARGET_SUFFIX[target]}", files)


def zip_project(folder: str, files: dict[str, str]) -> tuple[str, bytes]:
    """Zip ``files`` under ``folder/`` with fixed timestamps so identical input gives identical bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{folder}/{path}", date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[path])
    return folder, buffer.getvalue()


def _cases_json(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": str(c.get("name", f"case {i + 1}")), "input": c.get("input") or {},
         "assertions": c.get("assertions") or [], "seed": c.get("seed")}
        for i, c in enumerate(cases)
    ]


def _assertions_source() -> str:
    """The assertion engine from the AiFlow backend, made standalone for the generated tests."""
    source = inspect.getsource(assertions_module)
    replacements = [
        ("from pydantic import BaseModel\n", ""),
        ("from app.services import expressions, schema_utils\n", "import aiflow_expressions as expressions\nimport aiflow_schema as schema_utils\n"),
        ("class AssertionResult(BaseModel):", "@dataclass\nclass AssertionResult:"),
    ]
    for old, new in replacements:
        if old not in source:
            raise RuntimeError(f"assertions.py changed: cannot adapt it for export ({old.strip()!r} not found)")
        source = source.replace(old, new, 1)
    return source


class _Plan:
    """Everything derived from the workflow that the file builders share."""

    def __init__(self, workflow: Workflow, target: str = "langgraph"):
        self.workflow = workflow
        self.target = target
        by_id = {n.id: n for n in workflow.nodes}
        self.edges = [e for e in workflow.edges if e.source in by_id and e.target in by_id]

        if target == "mcp":
            # A tool server needs no START/END: every step is available, none is "reachable".
            self.start = None
            self.nodes = list(workflow.nodes)
            self.skipped = []
        else:
            starts = [n for n in workflow.nodes if n.type == NodeType.START]
            if len(starts) != 1:
                raise ExportError(f"The workflow needs exactly one START node to be exported (it has {len(starts)}).")
            if not any(n.type == NodeType.END for n in workflow.nodes):
                raise ExportError("The workflow needs at least one END node to be exported.")
            self.start = starts[0]

            # Only steps reachable from START are part of the graph.
            out: dict[str, list[str]] = {}
            for e in self.edges:
                out.setdefault(e.source, []).append(e.target)
            seen = {self.start.id}
            queue = deque([self.start.id])
            while queue:
                for nxt in out.get(queue.popleft(), []):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
            self.nodes = [n for n in workflow.nodes if n.id in seen]
            self.skipped = [n for n in workflow.nodes if n.id not in seen]

        used: set[str] = set()
        self.names = {n.id: _unique(_slug(n.id), used) for n in self.nodes}
        self.func = {n.id: f"run_{self.names[n.id]}" for n in self.nodes}

    # ── nodes.py ────────────────────────────────────────────────────────────
    def nodes_py(self) -> str:
        lines = [
            '"""One function per workflow step (generated by AiFlow).',
            "",
            "Each function receives the graph state and returns the part of it that changes. Step settings come",
            'from workflow.json through runtime.NODES, so edit the workflow there or in AiFlow."""',
            "from review import interrupt" if self.target == "python" else "from langgraph.types import interrupt",
            "",
            "import integrations",
            "from runtime import NODES, call_llm",
            "from state import State",
            "",
        ]
        for n in self.nodes:
            lines += ["", ""] + self._node_function(n)
        return "\n".join(lines) + "\n"

    def _node_function(self, n: WorkflowNode) -> list[str]:
        nid = repr(n.id)
        name = _safe_text(n.name, 60)
        fn = self.func[n.id]
        head = [f"def {fn}(state: State) -> dict:", f'    """{n.type.value}: {name}"""']
        t = n.type
        if t == NodeType.START:
            return head + [f"    return {{\"visited\": [{nid}]}}"]
        if t == NodeType.END:
            return head + [f"    return {{\"result\": state.get(\"data\", {{}}), \"visited\": [{nid}]}}"]
        if t == NodeType.CONDITION:
            return head + ["    # The branch is chosen by the router in routing.py.", f"    return {{\"visited\": [{nid}]}}"]
        if t == NodeType.HITL:
            return head + [
                "    config = NODES[%s].get(\"config\") or {}" % nid,
                "    decision = interrupt({",
                f"        \"step\": NODES[{nid}].get(\"name\"),",
                "        \"instructions\": config.get(\"instructions\"),",
                "        \"data\": state.get(\"data\", {}),",
                "    })",
                "    approved = str(decision).strip().lower() in {\"approve\", \"approved\", \"yes\", \"y\", \"true\"}",
                f"    return {{\"data\": {{\"approved\": approved, \"decision\": str(decision)}}, \"visited\": [{nid}]}}",
            ]
        if t == NodeType.LLM:
            return head + [
                f"    out = call_llm({nid}, state.get(\"data\", {{}}))",
                f"    return {{\"data\": out, \"visited\": [{nid}]}}",
            ]
        # TOOL / API / DATABASE / RAG / TRANSFORM → implemented in integrations.py
        return head + [
            f"    out = integrations.{self._stub_name(n)}(state.get(\"data\", {{}}))",
            f"    return {{\"data\": out, \"visited\": [{nid}]}}",
        ]

    def _stub_name(self, n: WorkflowNode) -> str:
        return f"{n.type.value.lower()}_{self.names[n.id]}"

    # ── integrations.py ─────────────────────────────────────────────────────
    @property
    def stubs(self) -> list[WorkflowNode]:
        return [n for n in self.nodes if n.type in (NodeType.TOOL, NodeType.API, NodeType.DATABASE, NodeType.RAG, NodeType.TRANSFORM)]

    @property
    def uses_connectors(self) -> bool:
        return any(n.type in (NodeType.API, NodeType.DATABASE, NodeType.RAG) for n in self.nodes)

    def integrations_py(self) -> str:
        lines = [
            '"""Steps that talk to the outside world (generated by AiFlow).',
            "",
            "With AIFLOW_MOCK=1 every function returns a fixture, so the graph runs offline. Without it:",
            "  * API, DATABASE and RAG steps do the real work through connectors.py, using the step's settings;",
            "  * TOOL and TRANSFORM steps have no settings that say how to run them, so they raise",
            "    NotImplementedError until you write them here.",
            'Return a dict: it is merged into the workflow data."""',
            "from typing import Any",
            "",
            "from runtime import NODES, fixture, mock_mode",
        ]
        if self.uses_connectors:
            lines.append("import connectors")
        if not self.stubs:
            lines += ["", "", "# This workflow has no TOOL, API, DATABASE, RAG or TRANSFORM steps, so there is nothing to implement."]
        for n in self.stubs:
            lines += ["", ""] + self._stub_function(n)
        return "\n".join(lines) + "\n"

    def _stub_function(self, n: WorkflowNode) -> list[str]:
        cfg = n.config
        nid = repr(n.id)
        t = n.type
        real: Optional[str] = None            # the call that does the work when mock mode is off
        if t == NodeType.TOOL:
            summary = f"runs the tool '{_safe_text(cfg.get('name') or n.name, 50)}'"
            default = self._tool_default(nid)
        elif t == NodeType.API:
            method = _safe_text(str(cfg.get("method") or "GET").upper(), 10)
            effect = "changes data in another system" if _is_irreversible(n) else "reads from another system"
            summary = f"{method} {_safe_text(cfg.get('url') or '(no url set)', 80)} ({effect})"
            default = _literal({"status": 200, "body": {"mock": True}, "_mock": True})
            real = "connectors.http_request(config, data)"
        elif t == NodeType.DATABASE:
            effect = "writes" if _is_irreversible(n) else "reads"
            summary = f"{effect} data with the query in the step's settings"
            default = _literal({"rows": [], "row_count": 0, "_mock": True})
            real = "connectors.run_query(config, data)"
        elif t == NodeType.RAG:
            summary = f"searches the knowledge base '{_safe_text(cfg.get('knowledgeBase') or '(none set)', 50)}'"
            default = _literal({"documents": [], "context": "", "_mock": True})
            real = "connectors.search_knowledge(config, data)"
        else:
            summary = f"reshapes the data ({_safe_text(cfg.get('description') or 'no description', 60)})"
            default = _literal({"_transformed": True})
        body = [
            f"def {self._stub_name(n)}(data: dict[str, Any]) -> dict[str, Any]:",
            f'    """{n.type.value} step \'{_safe_text(n.name, 50)}\': {summary}."""',
            f"    config = NODES[{nid}].get(\"config\") or {{}}   # the settings from the designer",
            "    if mock_mode():",
            f"        return fixture({nid}, {default})",
        ]
        if real:
            body.append(f"    return {real}")
        else:
            body += [
                "    # TODO: implement this step. `data` holds everything the workflow has produced so far;",
                "    # return a dict with the fields it adds.",
                f"    raise NotImplementedError(f\"Implement step {{NODES[{nid}].get('name')!r}} in integrations.py, or run with AIFLOW_MOCK=1.\")",
            ]
        return body

    @staticmethod
    def _tool_default(nid: str) -> str:
        return f"{{\"tool\": NODES[{nid}].get(\"name\"), \"result\": \"mock tool output\", \"_mock\": True}}"

    # ── requirements / environment ──────────────────────────────────────────
    def requirements(self) -> str:
        lines = [] if self.target == "python" else ["langgraph>=1.0,<2"]
        lines += ["langchain-openai>=1.0,<2", "python-dotenv>=1.0", "pytest>=8"]
        if any(n.type == NodeType.API for n in self.nodes):
            lines.append("httpx>=0.27")
        if any(n.type == NodeType.DATABASE for n in self.nodes):
            lines += ["sqlalchemy>=2,<3", "# add the driver for your database, for example: psycopg2-binary (PostgreSQL), pymysql (MySQL)"]
        return "\n".join(lines) + "\n"

    def env_names(self) -> list[str]:
        """Names of the environment variables the workflow refers to as ``env:NAME``."""
        found: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, str) and value.startswith("env:"):
                name = re.sub(r"[^A-Za-z0-9_]", "", value[4:])
                if name and name not in found:
                    found.append(name)
            elif isinstance(value, dict):
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)

        for n in self.nodes:
            if n.type in (NodeType.API, NodeType.DATABASE):
                visit(n.config)
        return found

    def env_example(self) -> str:
        extra = self.env_names()
        text = tpl.ENV_EXAMPLE
        if extra:
            text += "\n# Referenced by this workflow as env:NAME (never stored in workflow.json)\n" + "".join(f"{name}=\n" for name in extra)
        if any(n.type == NodeType.RAG for n in self.nodes):
            text += "\n# Knowledge search reads .md/.txt files from knowledge/<knowledge base>/. With OPENAI_API_KEY set it uses\n# embeddings; otherwise an offline keyword scorer. AIFLOW_RAG=keyword|embeddings overrides.\n# AIFLOW_KNOWLEDGE_DIR=knowledge\n"
        return text

    # ── routing.py ──────────────────────────────────────────────────────────
    def routing_py(self) -> str:
        lines = [
            '"""Branch selection for decision steps (generated by AiFlow)."""',
            "from runtime import choose_branches",
            "from state import State",
        ]
        conditions = [n for n in self.nodes if n.type == NodeType.CONDITION]
        if not conditions:
            lines += ["", "", "# This workflow has no decision steps."]
        for n in conditions:
            edges = [(e.condition, self.names[e.target]) for e in self.edges if e.source == n.id and e.target in self.names]
            const = f"BRANCHES_{self.names[n.id].upper()}"
            lines += [
                "", "",
                f"{const} = {_literal(edges)}   # (label, next step)",
                "", "",
                f"def route_{self.names[n.id]}(state: State) -> list[str]:",
                f'    """Choose the next step(s) after \'{_safe_text(n.name, 50)}\'."""',
                f"    return choose_branches({n.id!r}, {const}, state.get(\"data\", {{}}))",
            ]
        return "\n".join(lines) + "\n"

    # ── graph.py ────────────────────────────────────────────────────────────
    def graph_py(self) -> str:
        return self._plain_graph_py() if self.target == "python" else self._langgraph_graph_py()

    def _plain_graph_py(self) -> str:
        """The graph as plain data for engine.py: the entry step, plain edges, and a router per decision."""
        by_id = {n.id: n for n in self.nodes}
        edges: dict[str, list[str]] = {}
        for e in self.edges:
            src, dst = by_id.get(e.source), by_id.get(e.target)
            if not src or not dst or src.type in (NodeType.CONDITION, NodeType.END):
                continue
            targets = edges.setdefault(self.names[src.id], [])
            if self.names[dst.id] not in targets:
                targets.append(self.names[dst.id])
        routers = [n for n in self.nodes if n.type == NodeType.CONDITION]
        lines = [
            '"""The workflow graph as data (generated by AiFlow)."""',
            "import nodes",
            "import routing",
            "",
            f"ENTRY = {self.names[self.start.id]!r}",
            "",
            "FUNCS = {",
            *[f"    {self.names[n.id]!r}: nodes.{self.func[n.id]}," for n in self.nodes],
            "}",
            "",
            "# next steps after each step that is not a decision",
            f"EDGES = {_literal(edges)}",
            "",
            "# decisions pick their next steps with a router (see routing.py)",
            "ROUTERS = {",
            *[f"    {self.names[n.id]!r}: routing.route_{self.names[n.id]}," for n in routers],
            "}",
        ]
        return "\n".join(lines) + "\n"

    def _langgraph_graph_py(self) -> str:
        lines = [
            '"""Builds the LangGraph StateGraph for this workflow (generated by AiFlow)."""',
            "from langgraph.checkpoint.memory import InMemorySaver",
            "from langgraph.graph import END, START, StateGraph",
            "",
            "import nodes",
            "import routing",
            "from state import State",
            "",
            "",
            "def build_graph(checkpointer=None):",
            '    """Return the compiled graph. A checkpointer is required for human-review pauses; the default keeps them in memory."""',
            "    graph = StateGraph(State)",
        ]
        for n in self.nodes:
            lines.append(f"    graph.add_node({self.names[n.id]!r}, nodes.{self.func[n.id]})")
        lines += ["", f"    graph.add_edge(START, {self.names[self.start.id]!r})"]
        by_id = {n.id: n for n in self.nodes}
        added: set[tuple[str, str]] = set()
        for e in self.edges:
            if e.source not in by_id or e.target not in by_id or (e.source, e.target) in added:
                continue
            if by_id[e.source].type in (NodeType.CONDITION, NodeType.END):
                continue                                         # decisions are routed below; END goes to the graph's END
            added.add((e.source, e.target))
            lines.append(f"    graph.add_edge({self.names[e.source]!r}, {self.names[e.target]!r})")
        for n in self.nodes:
            if n.type == NodeType.CONDITION:
                lines.append(f"    graph.add_conditional_edges({self.names[n.id]!r}, routing.route_{self.names[n.id]})")
            elif n.type == NodeType.END:
                lines.append(f"    graph.add_edge({self.names[n.id]!r}, END)")
        lines += ["", "    return graph.compile(checkpointer=checkpointer or InMemorySaver())"]
        return "\n".join(lines) + "\n"

    # ── README.md ───────────────────────────────────────────────────────────
    def readme(self, has_cases: bool) -> str:
        wf = self.workflow
        stubs = [n for n in self.nodes if n.type in (NodeType.TOOL, NodeType.API, NodeType.DATABASE, NodeType.RAG, NodeType.TRANSFORM)]
        rows = ["| Step | Type | Function |", "|---|---|---|"]
        for n in self.nodes:
            fn = f"nodes.{self.func[n.id]}" + (f" → integrations.{self._stub_name(n)}" if n in stubs else "")
            rows.append(f"| {_safe_text(n.name, 50).replace('|', '/')} | {n.type.value} | `{fn}` |")
        todo_steps = [n for n in stubs if n.type in (NodeType.TOOL, NodeType.TRANSFORM)]
        todo = (
            ["", "## What you still need to implement", "",
             "These steps have no settings that say how to run them. They return fixtures in mock mode and raise "
             "`NotImplementedError` otherwise; write them in `integrations.py`:", ""]
            + [f"- `{self._stub_name(n)}` — {n.type.value} step “{_safe_text(n.name, 50)}”" for n in todo_steps]
            if todo_steps else []
        )
        real_steps = [n for n in stubs if n.type in (NodeType.API, NodeType.DATABASE, NodeType.RAG)]
        connect = (
            ["", "## What runs for real", "",
             "Outside mock mode these steps use `connectors.py` and the settings in `workflow.json`:", ""]
            + [f"- {n.type.value} “{_safe_text(n.name, 50)}” → `{self._stub_name(n)}`" for n in real_steps]
            + ["",
               "- **API**: sends the request (method, url, headers, body). `{{field}}` values in the url are percent-encoded; a header value `env:NAME` is read from that environment variable. A non-2xx response is returned as `{status, body}` so a decision can branch on it.",
               "- **DATABASE**: runs the query with SQLAlchemy; `{{field}}` values become bound parameters (never pasted into the SQL). Set the step's connection to `env:NAME`, with the database URL in that variable, and install your database driver.",
               "- **RAG**: searches `knowledge/<knowledge base>/*.md|*.txt` (embeddings if `OPENAI_API_KEY` is set, otherwise an offline keyword scorer). Swap in your vector store in `connectors.search_knowledge` when you have one."]
            if real_steps else []
        )
        skipped = (
            ["", f"Steps not connected to START were left out: {', '.join(_safe_text(n.name, 40) for n in self.skipped)}."]
            if self.skipped else []
        )
        tests = (
            "`tests/test_workflow.py` runs the workflow once and replays every case of the AiFlow test suite (`tests/cases.json`) "
            "with the same seeds and checks."
            if has_cases else
            "`tests/test_workflow.py` runs the workflow once on its sample input. Export with a test suite selected to also get one test per case."
        )
        return "\n".join([
            f"# {_safe_text(wf.name, 80)}",
            "",
            _safe_text(wf.description, 300) if wf.description.strip() else (
                "A workflow exported from AiFlow as a plain Python project (no framework; `engine.py` is the whole runtime)."
                if self.target == "python" else "A workflow exported from AiFlow as a LangGraph project."),
            "",
            "Generated by AiFlow. The workflow is kept in `workflow.json` and every step reads its settings from there.",
            "",
            "## Run it",
            "",
            "```bash",
            "python -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate",
            "pip install -r requirements.txt",
            "cp .env.example .env                                  # add OPENAI_API_KEY, or use mock mode",
            "",
            "python main.py --mock --input '{\"message\": \"hello\"}'  # offline, no API key",
            "python main.py --input-file input.json                # real LLM calls",
            "pytest                                                # tests, always in mock mode",
            "```",
            "",
            "Human-review steps ask `approve / reject` in the terminal (`--auto-approve` skips the prompt)."
            if self.target == "python" else
            "Human-review steps pause the run and ask `approve / reject` in the terminal (`--auto-approve` skips the prompt).",
            "",
            "## Steps",
            "",
            *rows,
            *skipped,
            *connect,
            *todo,
            "",
            "## Tests",
            "",
            tests,
            "",
            "## Differences from the AiFlow simulator",
            "",
            *[f"- {d}" for d in (PLAIN_DIFFERENCES if self.target == "python" else DIFFERENCES)],
            "",
            "Decision expressions are evaluated by `aiflow_expressions.py`, the same safe evaluator the simulator uses (no `eval`).",
            "",
        ])

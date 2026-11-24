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
from app.services import langgraph_templates as tpl
from app.services import schema_utils as schema_module
from app.services.linter import _is_irreversible

DIFFERENCES = [
    "State accumulates: each step's output is merged into the running data, so later steps can use earlier results. "
    "The simulator passes only the previous step's output.",
    "When a decision matches no branch the generated code raises RoutingError; the simulator explores every branch.",
    "Steps with several outgoing edges run those branches in parallel. If separate parallel branches rejoin, "
    "the joining step runs once per arriving branch.",
    "TOOL, API, DATABASE, RAG and TRANSFORM steps are stubs that return fixtures until you implement them in integrations.py.",
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
    def export(
        self,
        workflow: Workflow,
        cases: Optional[list[dict[str, Any]]] = None,
        run_seed: int = 0,
    ) -> dict[str, str]:
        """Return the project as ``{relative path: file text}``."""
        plan = _Plan(workflow)
        files: dict[str, str] = {
            "workflow.json": json.dumps(workflow.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            "state.py": tpl.STATE_PY,
            "runtime.py": tpl.RUNTIME_PY,
            "aiflow_expressions.py": inspect.getsource(expressions_module),
            "aiflow_schema.py": inspect.getsource(schema_module),
            "nodes.py": plan.nodes_py(),
            "integrations.py": plan.integrations_py(),
            "routing.py": plan.routing_py(),
            "graph.py": plan.graph_py(),
            "main.py": tpl.MAIN_PY,
            "requirements.txt": tpl.REQUIREMENTS,
            ".env.example": tpl.ENV_EXAMPLE,
            "pytest.ini": tpl.PYTEST_INI,
            "README.md": plan.readme(has_cases=bool(cases)),
            "tests/aiflow_assertions.py": _assertions_source(),
            "tests/cases.json": json.dumps(_cases_json(cases or []), indent=2, ensure_ascii=False) + "\n",
            "tests/test_workflow.py": tpl.TEST_PY.replace("__RUN_SEED__", str(int(run_seed))),
        }
        return files

    def export_zip(self, workflow: Workflow, cases: Optional[list[dict[str, Any]]] = None, run_seed: int = 0) -> tuple[str, bytes]:
        """Return ``(project folder name, zip bytes)``. Deterministic: the same input gives identical bytes."""
        files = self.export(workflow, cases, run_seed)
        folder = f"{_project_slug(workflow.name)}-langgraph"
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

    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        starts = [n for n in workflow.nodes if n.type == NodeType.START]
        if len(starts) != 1:
            raise ExportError(f"The workflow needs exactly one START node to be exported (it has {len(starts)}).")
        if not any(n.type == NodeType.END for n in workflow.nodes):
            raise ExportError("The workflow needs at least one END node to be exported.")
        self.start = starts[0]

        by_id = {n.id: n for n in workflow.nodes}
        self.edges = [e for e in workflow.edges if e.source in by_id and e.target in by_id]

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
            "from langgraph.types import interrupt",
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
    def integrations_py(self) -> str:
        lines = [
            '"""Stubs for the steps that talk to the outside world (generated by AiFlow).',
            "",
            "Every function below returns a fixture so the graph runs end to end today. Replace the body with a",
            "real implementation; the step's settings from the designer are in NODES[<id>]['config']. Return a dict:",
            'it is merged into the workflow data."""',
            "from typing import Any",
            "",
            "from runtime import NODES, fixture",
        ]
        stubs = [n for n in self.nodes if n.type in (NodeType.TOOL, NodeType.API, NodeType.DATABASE, NodeType.RAG, NodeType.TRANSFORM)]
        if not stubs:
            lines += ["", "", "# This workflow has no TOOL, API, DATABASE, RAG or TRANSFORM steps, so there is nothing to implement."]
        for n in stubs:
            lines += ["", ""] + self._stub_function(n)
        return "\n".join(lines) + "\n"

    def _stub_function(self, n: WorkflowNode) -> list[str]:
        cfg = n.config
        nid = repr(n.id)
        t = n.type
        if t == NodeType.TOOL:
            summary = f"runs the tool '{_safe_text(cfg.get('name') or n.name, 50)}'"
            hint = ["    # TODO: call the tool and return its result as a dict."]
            default = None   # built from the step's name at run time, see below
        elif t == NodeType.API:
            method = _safe_text(str(cfg.get("method") or "GET").upper(), 10)
            summary = f"{method} {_safe_text(cfg.get('url') or '(no url set)', 80)}"
            effect = "changes data in another system" if _is_irreversible(n) else "reads from another system"
            hint = [
                f"    # TODO: this step {effect}. Send the request described in NODES[{nid}]['config'] (method, url, headers),",
                "    # for example with httpx, filling {{placeholders}} in the url with runtime.render(...).",
            ]
            default = {"status": 200, "body": {"mock": True}, "_mock": True}
        elif t == NodeType.DATABASE:
            effect = "writes" if _is_irreversible(n) else "reads"
            summary = f"{effect} data with the query in the step's settings"
            hint = [f"    # TODO: run the query in NODES[{nid}]['config']['query'] against your database (connection: config['connection'])."]
            default = {"rows": [], "_mock": True}
        elif t == NodeType.RAG:
            summary = f"searches the knowledge base '{_safe_text(cfg.get('knowledgeBase') or '(none set)', 50)}'"
            hint = [f"    # TODO: query your vector store for NODES[{nid}]['config']['knowledgeBase'] and return {{'documents': [...], 'answer': ...}}."]
            default = {"documents": [], "answer": "Mock RAG answer", "_mock": True}
        else:
            summary = f"reshapes the data ({_safe_text(cfg.get('description') or 'no description', 60)})"
            hint = ["    # TODO: transform `data` and return the fields that change."]
            default = {"_transformed": True}
        return [
            f"def {self._stub_name(n)}(data: dict[str, Any]) -> dict[str, Any]:",
            f'    """{n.type.value} step \'{_safe_text(n.name, 50)}\': {summary}."""',
            f"    config = NODES[{nid}].get(\"config\") or {{}}   # the settings from the designer",
            *hint,
            f"    return fixture({nid}, {_literal(default) if default is not None else self._tool_default(nid)})",
        ]

    @staticmethod
    def _tool_default(nid: str) -> str:
        return f"{{\"tool\": NODES[{nid}].get(\"name\"), \"result\": \"mock tool output\", \"_mock\": True}}"

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
        todo = (
            ["", "## What you still need to implement", "",
             "These steps return fixtures until you replace the bodies in `integrations.py`:", ""]
            + [f"- `{self._stub_name(n)}` — {n.type.value} step “{_safe_text(n.name, 50)}”" for n in stubs]
            if stubs else []
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
            _safe_text(wf.description, 300) if wf.description.strip() else "A workflow exported from AiFlow as a LangGraph project.",
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
            "Human-review steps pause the run and ask `approve / reject` in the terminal (`--auto-approve` skips the prompt).",
            "",
            "## Steps",
            "",
            *rows,
            *skipped,
            *todo,
            "",
            "## Tests",
            "",
            tests,
            "",
            "## Differences from the AiFlow simulator",
            "",
            *[f"- {d}" for d in DIFFERENCES],
            "",
            "Decision expressions are evaluated by `aiflow_expressions.py`, the same safe evaluator the simulator uses (no `eval`).",
            "",
        ])

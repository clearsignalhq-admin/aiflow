"""Importing LangGraph code into a workflow (Task 57). The code is parsed, never executed."""
import glob
import json
import os
import textwrap
from collections import Counter
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow
from app.services.langgraph_exporter import LangGraphExporter
from app.services.langgraph_importer import MAX_FILES, import_langgraph
from tests.test_langgraph_exporter import E, N, routed_workflow

BASE = "http://test"
EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def imp(source: str, **extra):
    return import_langgraph({"graph.py": textwrap.dedent(source), **extra})


def types(result) -> dict[str, str]:
    return {n.id: n.type.value for n in result.workflow.nodes}


def edges(result) -> set[tuple]:
    return {(e.source, e.target, e.condition) for e in result.workflow.edges}


TRIAGE = '''
"""Support triage."""
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
import requests

def classify(state):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return {"category": llm.invoke("You are a support triage assistant. Classify the message.").content}

def lookup(state):
    return {"customer": requests.get("https://api.example.com/customers/1").json()}

def route(state):
    return "escalate" if state.get("category") == "billing" else "reply"

def escalate(state):
    return interrupt({"instructions": "Check the invoice"})

def reply(state):
    return {"done": True}

builder = StateGraph(dict)
builder.add_node("classify", classify)
builder.add_node("lookup", lookup)
builder.add_node("escalate", escalate)
builder.add_node("reply", reply)
builder.add_edge(START, "classify")
builder.add_edge("classify", "lookup")
builder.add_conditional_edges("lookup", route, {"escalate": "escalate", "reply": "reply"})
builder.add_edge("escalate", "reply")
builder.add_edge("reply", END)
graph = builder.compile()
'''


# ── The common case ──────────────────────────────────────────────────────────

def test_a_typical_graph_becomes_a_workflow():
    r = imp(TRIAGE)
    assert r.errors == [] and r.mode == "inferred"
    assert types(r) == {"start": "START", "classify": "LLM", "lookup": "API", "escalate": "HITL", "reply": "TRANSFORM",
                        "route_lookup": "CONDITION", "end": "END"}
    assert edges(r) == {("start", "classify", None), ("classify", "lookup", None), ("lookup", "route_lookup", None),
                        ("route_lookup", "escalate", "escalate"), ("route_lookup", "reply", "reply"),
                        ("escalate", "reply", None), ("reply", "end", None)}
    assert r.workflow.description == "Support triage."


def test_settings_that_are_plain_literals_are_carried_over():
    r = imp(TRIAGE)
    cfg = {n.id: n.config for n in r.workflow.nodes}
    assert cfg["classify"] == {"model": "gpt-4o-mini", "temperature": 0, "prompt": "You are a support triage assistant. Classify the message."}
    assert cfg["lookup"] == {"method": "GET", "url": "https://api.example.com/customers/1"}
    assert cfg["escalate"] == {"instructions": "Check the invoice"}
    assert {n.id: n.name for n in r.workflow.nodes}["classify"] == "Classify"


def test_a_simple_router_function_becomes_a_working_expression():
    r = imp(TRIAGE)
    expression = next(n for n in r.workflow.nodes if n.type == NodeType.CONDITION).config["expression"]
    assert expression == "'escalate' if input.category == 'billing' else 'reply'"
    from app.services import expressions
    assert expressions.evaluate(expression, {"input": {"category": "billing"}}) == "escalate"
    assert expressions.evaluate(expression, {"input": {"category": "x"}}) == "reply"


def test_the_result_is_a_valid_workflow_that_validates_and_simulates():
    import asyncio
    from app.schemas.simulation import SimulationSettings
    from app.services.simulator import simulate
    from app.services.validator import validate_workflow

    r = imp(TRIAGE)
    assert validate_workflow(r.workflow).valid
    trace = asyncio.run(simulate(r.workflow, {}, SimulationSettings()))
    assert trace.status == "complete"


def test_the_inferred_types_are_reported_so_the_user_can_check_them():
    warnings = " ".join(imp(TRIAGE).warnings)
    assert "inferred from the code" in warnings and "classify (LLM)" in warnings and "lookup (API)" in warnings
    assert "plain literals" in warnings


# ── Builder styles ───────────────────────────────────────────────────────────

def test_chained_builders_entry_finish_sequence_and_constants():
    r = imp('''
        from langgraph.graph import StateGraph
        NAME = "writer"
        def build():
            g = (StateGraph(dict)
                 .add_node(NAME, lambda s: s)
                 .add_node("critic", lambda s: s))
            g.add_node("publisher", lambda s: s)
            g.set_entry_point(NAME)
            g.add_edge(NAME, "critic")
            g.add_edge("critic", "publisher")
            g.set_finish_point("publisher")
            return g.compile()
    ''')
    assert r.errors == [] and set(types(r)) == {"start", "writer", "critic", "publisher", "end"}
    assert edges(r) == {("start", "writer", None), ("writer", "critic", None), ("critic", "publisher", None), ("publisher", "end", None)}


def test_add_sequence_and_unnamed_add_node():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        def alpha(s): return s
        def beta(s): return s
        def gamma(s): return s
        b = StateGraph(dict)
        b.add_node(alpha)
        b.add_sequence([beta, ("gamma", gamma)])
        b.add_edge(START, "alpha")
        b.add_edge("alpha", "beta")
        b.add_edge("gamma", END)
    ''')
    assert set(types(r)) >= {"alpha", "beta", "gamma"}
    assert {("alpha", "beta", None), ("beta", "gamma", None), ("gamma", "end", None)} <= edges(r)


def test_edges_from_a_list_join_branches():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        for n in ("a", "b", "c"):
            pass
        b.add_node("a", lambda s: s); b.add_node("b", lambda s: s); b.add_node("c", lambda s: s)
        b.add_edge(START, "a"); b.add_edge(START, "b")
        b.add_edge(["a", "b"], "c")
        b.add_edge("c", END)
    ''')
    assert {("a", "c", None), ("b", "c", None), ("start", "a", None), ("start", "b", None)} <= edges(r)


def test_routers_without_a_map_use_the_names_they_return_and_end_is_understood():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        def decide(state):
            if state["score"] > 5:
                return "approve"
            elif state["score"] > 2:
                return "review"
            return END
        b = StateGraph(dict)
        b.add_node("approve", lambda s: s); b.add_node("review", lambda s: s)
        b.add_edge(START, "approve")
        b.add_conditional_edges("approve", decide)
        b.add_edge("review", END)
    ''')
    cond = next(n for n in r.workflow.nodes if n.type == NodeType.CONDITION)
    assert cond.config["expression"] == "'approve' if input.score > 5 else 'review' if input.score > 2 else '__end__'"
    labels = {e.condition: e.target for e in r.workflow.edges if e.source == cond.id}
    assert labels == {"approve": "approve", "review": "review", "__end__": "end"}


def test_a_passthrough_step_that_only_anchors_a_decision_becomes_the_decision():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        def gate(state): return {"visited": ["gate"]}
        def pick(state): return "left" if state["x"] else "right"
        b = StateGraph(dict)
        b.add_node("gate", gate); b.add_node("left", lambda s: s); b.add_node("right", lambda s: s)
        b.add_edge(START, "gate")
        b.add_conditional_edges("gate", pick, {"left": "left", "right": "right"})
        b.add_edge("left", END); b.add_edge("right", END)
    ''')
    assert types(r)["gate"] == "CONDITION" and not any(i.startswith("route_") for i in types(r))
    assert ("gate", "left", "left") in edges(r)


def test_a_step_that_does_real_work_before_deciding_gets_a_separate_decision():
    r = imp(TRIAGE)
    assert types(r)["lookup"] == "API" and types(r)["route_lookup"] == "CONDITION"


def test_message_graph_is_recognised():
    assert imp('''
        from langgraph.graph import MessageGraph, START, END
        g = MessageGraph(); g.add_node("only", lambda s: s); g.add_edge(START, "only"); g.add_edge("only", END)
    ''').workflow is not None


# ── Router translation and its limits ────────────────────────────────────────

@pytest.mark.parametrize("body,expected", [
    ('return "a" if state["n"] >= 3 else "b"', "'a' if input.n >= 3 else 'b'"),
    ('return "a" if state.get("ok") and not state.get("blocked") else "b"', "'a' if input.ok and (not input.blocked) else 'b'"),
    ('if state["tier"] in ["gold", "silver"]:\n    return "a"\nreturn "b"', "'a' if input.tier in ['gold', 'silver'] else 'b'"),
    ('return "a" if state["order"]["total"] > 10 else "b"', "'a' if input.order.total > 10 else 'b'"),
    ('return "a" if state["my-key"] == 1 else "b"', "'a' if input['my-key'] == 1 else 'b'"),
    ('return "a" if state.count > 3 else "b"', "'a' if input.count > 3 else 'b'"),
])
def test_router_functions_are_translated(body, expected):
    src = f'''
        from langgraph.graph import StateGraph, START, END
        def router(state):
{textwrap.indent(textwrap.dedent(body), " " * 12)}
        b = StateGraph(dict)
        b.add_node("s", lambda x: x); b.add_node("a", lambda x: x); b.add_node("b", lambda x: x)
        b.add_edge(START, "s"); b.add_conditional_edges("s", router, {{"a": "a", "b": "b"}}); b.add_edge("a", END); b.add_edge("b", END)
    '''
    r = import_langgraph({"graph.py": textwrap.dedent(src)})
    assert next(n for n in r.workflow.nodes if n.type == NodeType.CONDITION).config["expression"] == expected


@pytest.mark.parametrize("body", [
    'return "a" if len(state["items"]) > 1 else "b"',
    'for x in state["items"]:\n    return "a"\nreturn "b"',
    'value = compute(state)\nreturn "a" if value else "b"',
    'return some_function(state)',
    'return "a" if state["n"] ** 2 > 3 else "b"',
])
def test_routers_that_are_not_simple_are_left_blank_with_a_clear_warning(body):
    src = f'''
        from langgraph.graph import StateGraph, START, END
        def router(state):
{textwrap.indent(textwrap.dedent(body), " " * 12)}
        b = StateGraph(dict)
        b.add_node("s", lambda x: x); b.add_node("a", lambda x: x); b.add_node("b", lambda x: x)
        b.add_edge(START, "s"); b.add_conditional_edges("s", router, {{"a": "a", "b": "b"}}); b.add_edge("a", END); b.add_edge("b", END)
    '''
    r = import_langgraph({"graph.py": textwrap.dedent(src)})
    cond = next(n for n in r.workflow.nodes if n.type == NodeType.CONDITION)
    assert cond.config == {} and any("could not be turned into an expression" in w for w in r.warnings)
    assert {e.condition for e in r.workflow.edges if e.source == cond.id} == {"a", "b"}      # the branches are still there


# ── Guessing a step's type ───────────────────────────────────────────────────

@pytest.mark.parametrize("body,expected,config", [
    ('interrupt({"instructions": "Approve it"})', "HITL", {"instructions": "Approve it"}),
    ('cur = conn.cursor(); cur.execute("SELECT id FROM orders WHERE id = 1")', "DATABASE", {"query": "SELECT id FROM orders WHERE id = 1", "connection": "env:DB_URL"}),
    ('docs = vectorstore.similarity_search(q, k=3)', "RAG", {"topK": 3}),
    ('r = httpx.post("https://x.test/orders")', "API", {"method": "POST", "url": "https://x.test/orders"}),
    ('r = requests.delete("https://x.test/orders/1")', "API", {"method": "DELETE", "url": "https://x.test/orders/1"}),
    ('llm = init_chat_model("gpt-4o-mini")\nllm.invoke("Answer politely and briefly to every customer message.")', "LLM", {"prompt": "Answer politely and briefly to every customer message."}),
    ('return ToolNode(tools).invoke(state)', "TOOL", None),
    ('x = 1\nreturn {"x": x}', "TRANSFORM", None),
])
def test_step_types_are_guessed_from_what_the_function_does(body, expected, config):
    r = imp(f'''
        from langgraph.graph import StateGraph, START, END
        def work(state):
{textwrap.indent(body, " " * 12)}
        b = StateGraph(dict)
        b.add_node("work", work); b.add_edge(START, "work"); b.add_edge("work", END)
    ''')
    node = next(n for n in r.workflow.nodes if n.id == "work")
    assert node.type.value == expected
    if config is not None:
        for key, value in config.items():
            assert node.config[key] == value


def test_decorated_tools_and_docstrings():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        @tool
        def search(state):
            """Look things up on the web."""
            return state
        def tidy(state):
            """Remove duplicate rows."""
            return state
        b = StateGraph(dict)
        b.add_node("search", search); b.add_node("tidy", tidy)
        b.add_edge(START, "search"); b.add_edge("search", "tidy"); b.add_edge("tidy", END)
    ''')
    nodes = {n.id: n for n in r.workflow.nodes}
    assert nodes["search"].type == NodeType.TOOL and nodes["search"].config["description"] == "Look things up on the web."
    assert nodes["tidy"].type == NodeType.TRANSFORM and nodes["tidy"].config["description"] == "Remove duplicate rows."


def test_function_in_another_file_is_found():
    r = import_langgraph({
        "graph.py": "from langgraph.graph import StateGraph, START, END\nfrom steps import fetch\nb = StateGraph(dict)\nb.add_node('fetch', fetch)\nb.add_edge(START, 'fetch')\nb.add_edge('fetch', END)\n",
        "steps.py": "import requests\ndef fetch(state):\n    return requests.get('https://x.test/a').json()\n",
    })
    assert types(r)["fetch"] == "API" and next(n for n in r.workflow.nodes if n.id == "fetch").config["url"] == "https://x.test/a"


# ── Gaps in the graph are reported, not silently invented ────────────────────

def test_missing_entry_and_finish_are_filled_in_with_warnings():
    r = imp('''
        from langgraph.graph import StateGraph
        b = StateGraph(dict)
        b.add_node("a", lambda s: s); b.add_node("b", lambda s: s)
        b.add_edge("a", "b")
    ''')
    assert edges(r) == {("a", "b", None), ("start", "a", None), ("b", "end", None)}
    joined = " ".join(r.warnings)
    assert "no entry point" in joined and "No step leads to END" in joined


def test_a_step_used_in_an_edge_but_never_added_is_created_with_a_warning():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        b.add_node("a", lambda s: s)
        b.add_edge(START, "a"); b.add_edge("a", "ghost"); b.add_edge("ghost", END)
    ''')
    assert "ghost" in types(r) and any("'ghost' is used in an edge but never added" in w for w in r.warnings)


def test_names_computed_at_run_time_are_counted_not_guessed():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        b.add_node("a", lambda s: s)
        for name in ("x", "y"):
            b.add_node(name, lambda s: s)
            b.add_edge("a", name)
        b.add_edge(START, "a"); b.add_edge("a", END)
    ''')
    assert any("computed at run time" in w for w in r.warnings)


def test_unsupported_methods_are_mentioned():
    r = imp('''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        b.add_node("a", lambda s: s); b.add_edge(START, "a"); b.add_edge("a", END)
        b.set_conditional_entry_point(lambda s: "a")
    ''')
    assert any("set_conditional_entry_point is not supported" in w for w in r.warnings)


# ── Errors and limits ────────────────────────────────────────────────────────

def test_clear_errors_for_the_common_mistakes():
    assert import_langgraph({}).errors == ["Add at least one Python file."]
    assert "No LangGraph StateGraph was found" in imp("x = 1\n").errors[0]
    broken = import_langgraph({"graph.py": "def broken(:\n  pass\n"})
    assert broken.workflow is None and "graph.py: line 1" in broken.errors[0]
    assert "No LangGraph StateGraph was found" in import_langgraph({"notes.txt": "StateGraph(dict)"}).errors[0]      # only .py files are read


def test_a_file_that_does_not_parse_is_skipped_but_the_rest_imports():
    r = import_langgraph({
        "graph.py": textwrap.dedent(TRIAGE),
        "broken.py": "def oops(:\n",
    })
    assert r.workflow is not None and r.errors == []
    assert any(w.startswith("Skipped broken.py: line 1") for w in r.warnings)


def test_size_limits():
    assert "Too many files" in import_langgraph({f"f{i}.py": "x=1" for i in range(MAX_FILES + 1)}).errors[0]
    assert "too large" in import_langgraph({"graph.py": "x = 1\n" * 50_000}).errors[0]
    many = "from langgraph.graph import StateGraph, START, END\nb = StateGraph(dict)\n" + "\n".join(f"b.add_node('n{i}', lambda s: s)" for i in range(101))
    assert "too large to import" in import_langgraph({"graph.py": many}).errors[0]


def test_deeply_nested_code_is_an_error_not_a_crash():
    r = import_langgraph({"graph.py": "x = " + "(" * 3000 + "1" + ")" * 3000})
    assert r.workflow is None and r.errors


def test_the_code_is_never_executed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = import_langgraph({"graph.py": textwrap.dedent('''
        import os
        open("PWNED", "w").write("x")
        __import__("os").system("echo pwned > PWNED2")
        from langgraph.graph import StateGraph, START, END
        def node(state):
            open("PWNED3", "w").write("x")
            return state
        b = StateGraph(dict)
        b.add_node("node", node); b.add_edge(START, "node"); b.add_edge("node", END)
        node({})
    ''')})
    assert r.workflow is not None
    assert not list(tmp_path.glob("PWNED*"))


def test_hostile_names_are_data():
    evil = "x'); import os; os.system('echo hi'); ('"
    r = imp(f'''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        b.add_node({evil!r}, lambda s: s); b.add_edge(START, {evil!r}); b.add_edge({evil!r}, END)
    ''')
    assert r.workflow is not None and any(n.name.startswith("X'") for n in r.workflow.nodes)


def test_long_names_are_truncated_to_fit_the_model():
    r = imp(f'''
        from langgraph.graph import StateGraph, START, END
        b = StateGraph(dict)
        b.add_node("{'n' * 300}", lambda s: s); b.add_edge(START, "{'n' * 300}"); b.add_edge("{'n' * 300}", END)
    ''')
    assert r.workflow is not None and all(len(n.id) <= 100 for n in r.workflow.nodes)


# ── AiFlow's own exports ─────────────────────────────────────────────────────

@pytest.mark.parametrize("target", ["langgraph", "python"])
def test_an_aiflow_export_is_restored_exactly_from_workflow_json(target):
    original = routed_workflow()
    files = LangGraphExporter().export(original, target=target)
    r = import_langgraph(files)
    assert r.mode == "exact" and r.workflow.model_dump(mode="json") == original.model_dump(mode="json")
    assert "restored exactly" in r.warnings[0]


def test_a_broken_workflow_json_falls_back_to_reading_the_code():
    files = LangGraphExporter().export(routed_workflow())
    files["workflow.json"] = "{not json"
    r = import_langgraph(files)
    assert r.mode == "inferred" and r.workflow is not None
    empty = dict(files, **{"workflow.json": json.dumps({"nodes": [], "edges": []})})
    assert import_langgraph(empty).mode == "inferred"


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(EXAMPLES, "**", "*.json"), recursive=True)))
def test_aiflow_code_without_workflow_json_still_gives_the_same_shape(path):
    """Read the generated code the way a stranger's code is read: types and branching come back."""
    original = Workflow(**json.load(open(path, encoding="utf-8")))
    files = LangGraphExporter().export(original)
    del files["workflow.json"]
    r = import_langgraph(files)
    assert r.errors == [] and r.mode == "inferred", r.errors
    assert Counter(n.type.value for n in r.workflow.nodes) == Counter(n.type.value for n in original.nodes)
    assert len(r.workflow.edges) == len(original.edges)
    assert Counter(e.condition for e in r.workflow.edges if e.condition) == Counter(e.condition for e in original.edges if e.condition)


# ── Endpoint ─────────────────────────────────────────────────────────────────

async def post(body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        return await client.post("/api/workflows/import/langgraph", json=body)


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_imports_and_returns_warnings():
    res = await post({"files": {"graph.py": TRIAGE}})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "inferred" and len(body["workflow"]["nodes"]) == 7 and body["warnings"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_exact_mode_and_errors():
    exact = await post({"files": LangGraphExporter().export(routed_workflow())})
    assert exact.json()["mode"] == "exact"
    none = await post({"files": {"graph.py": "x = 1"}})
    assert none.status_code == 422 and "No LangGraph StateGraph was found" in none.json()["detail"]
    assert (await post({"files": {}})).status_code == 422
    too_many = await post({"files": {f"f{i}.py": "x" for i in range(21)}})
    assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_requires_auth():
    assert (await post({"files": {"graph.py": TRIAGE}})).status_code in (401, 403)

"""Tests for the deterministic workflow explainer (Task 52)."""
import glob
import json
import os
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.services.explainer import _duration, _order, explain_workflow

BASE = "http://test"
EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(s, t, c=None):
    return WorkflowEdge(source=s, target=t, condition=c)


def md(workflow) -> str:
    return explain_workflow(workflow)


def section(text: str, title: str) -> str:
    match = re.search(rf"## {re.escape(title)}\n(.*?)(?=\n## |\Z)", text, re.S)
    assert match, f"missing section {title!r}"
    return match.group(1)


def simple() -> Workflow:
    return Workflow(name="Greeter", description="Says hello.", nodes=[N("s", NodeType.START, "Start"), N("e", NodeType.END, "End")],
                    edges=[E("s", "e")])


# ── Examples ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(EXAMPLES, "**", "*.json"), recursive=True)))
def test_every_example_produces_a_complete_deterministic_document(path):
    wf = Workflow(**json.load(open(path, encoding="utf-8")))
    text = md(wf)
    assert text == md(wf)                                              # same input, same text
    assert text.startswith(f"# {wf.name}")
    for title in ("At a glance", "How it works", "People in the loop", "What it connects to", "Things to check"):
        assert f"## {title}" in text
    steps = section(text, "How it works")
    for node in wf.nodes:
        assert f"**{node.name}**" in steps                              # every connected step is described
    assert "\r" not in text and text.endswith("\n")


def test_steps_are_numbered_consecutively_in_flow_order():
    wf = Workflow(**json.load(open(os.path.join(EXAMPLES, "medium", "customer-support.json"), encoding="utf-8")))
    numbered = re.findall(r"^(\d+)\. \*\*(.+?)\*\*", section(md(wf), "How it works"), re.M)
    assert [int(n) for n, _ in numbered] == list(range(1, len(wf.nodes) + 1))
    names = [name for _, name in numbered]
    assert names.index("Human Review") < names.index("Generate Response")   # a step follows everything that feeds it
    assert names[0] == "Start" and names[-1] == "End"


# ── Structure and wording ────────────────────────────────────────────────────

def test_header_summary_and_glance_table():
    text = md(simple())
    assert text.startswith("# Greeter\n\nSays hello.\n\nIn short: 0 steps.")
    glance = section(text, "At a glance")
    assert "| Steps | 0 |" in glance and "| Human reviews | 0 |" in glance
    assert "Rough time per run" in glance


def test_empty_workflow():
    assert "no steps yet" in md(Workflow(name="Empty"))


def test_decision_lists_each_branch_and_unlabelled_branch_is_otherwise():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Route", config={"expression": "input.amount > 100"}),
               N("a", NodeType.TRANSFORM, "Approve"), N("b", NodeType.TRANSFORM, "Reject"), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "a", "big"), E("c", "b"), E("a", "e"), E("b", "e")],
    )
    steps = section(md(wf), "How it works")
    assert "makes a decision using `input.amount > 100`" in steps
    assert "- if **big**: go to **Approve**" in steps
    assert "- otherwise: go to **Reject**" in steps


def test_parallel_and_dead_end_and_unconnected():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("dead", NodeType.TRANSFORM, "Dead"),
               N("orphan", NodeType.LLM, "Orphan"), N("e", NodeType.END)],
        edges=[E("s", "a"), E("s", "b"), E("a", "e"), E("b", "dead")],
    )
    text = md(wf)
    steps = section(text, "How it works")
    assert "Then, in parallel: **A** and **B**" in steps
    assert "nothing is connected after this step" in steps
    assert "**Not connected to the start** (these never run): **Orphan**." in steps
    assert "Orphan" in section(text, "Things to check")                 # the linter agrees


def test_cycles_do_not_hang_and_every_step_is_listed_once():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "b"), E("b", "a"), E("b", "e")],
    )
    reachable, rest = _order(wf)
    assert sorted(n.id for n in reachable) == ["a", "b", "e", "s"] and rest == []
    assert len(re.findall(r"^\d+\. ", section(md(wf), "How it works"), re.M)) == 4
    assert "Cycle detected" in section(md(wf), "Things to check")


def test_describes_every_node_type_in_plain_language():
    wf = Workflow(
        metadata={"sample_input": {"message": "hi", "customerId": "1"}},
        nodes=[
            N("s", NodeType.START),
            N("l", NodeType.LLM, "Draft", config={"model": "gpt-4o-mini", "prompt": "Write a polite   reply\nto the customer"},
              output_schema={"type": "object", "properties": {"reply": {"type": "string"}, "score": {"type": "number"}}}),
            N("t", NodeType.TOOL, "Search", config={"name": "web_search", "description": "looks things up"}),
            N("a", NodeType.API, "Notify", config={"method": "post", "url": "https://x.test/notify"}),
            N("d", NodeType.DATABASE, "Save", config={"query": "INSERT INTO t VALUES (1)"}),
            N("r", NodeType.RAG, "Docs", config={"knowledgeBase": "policies", "topK": 3}),
            N("h", NodeType.HITL, "Approve", config={"instructions": "Check the tone"}),
            N("x", NodeType.TRANSFORM, "Tidy", config={"description": "remove duplicates"}),
            N("e", NodeType.END),
        ],
        edges=[E("s", "l"), E("l", "t"), E("t", "a"), E("a", "d"), E("d", "r"), E("r", "h"), E("h", "x"), E("x", "e")],
    )
    text = md(wf)
    steps = section(text, "How it works")
    assert "expects input such as: `message`, `customerId`" in steps
    assert "asks an AI model (gpt-4o-mini). Instruction: “Write a polite reply to the customer”" in steps   # whitespace collapsed
    assert "Produces `reply` (string), `score` (number)." in steps
    assert "runs the tool `web_search` — looks things up." in steps
    assert "calls an external service: POST `https://x.test/notify` — changes data in another system." in steps
    assert "runs a database query that changes stored data. Query: `INSERT INTO t VALUES (1)`" in steps
    assert "searches the knowledge base `policies`, keeping the top 3 matches." in steps
    assert "pauses until a person reviews it. Instructions: “Check the tone”" in steps
    assert "reshapes the data: remove duplicates." in steps

    assert "- **Approve** — “Check the tone”" in section(text, "People in the loop")
    connections = section(text, "What it connects to")
    assert "| Notify | external service call | POST https://x.test/notify | writes |" in connections
    assert "| Save | database query | INSERT INTO t VALUES (1) | writes |" in connections
    assert "| Docs | knowledge search | policies | reads |" in connections
    assert "| Search | tool | web_search | unknown |" in connections


def test_reads_are_not_reported_as_writes():
    wf = Workflow(nodes=[N("s", NodeType.START), N("a", NodeType.API, "Get", config={"method": "GET", "url": "u"}),
                         N("d", NodeType.DATABASE, "Read", config={"query": "SELECT 1"}), N("e", NodeType.END)],
                  edges=[E("s", "a"), E("a", "d"), E("d", "e")])
    text = md(wf)
    assert "reads from another system" in text and "reads stored data" in text and "writes" not in section(text, "What it connects to")


def test_no_humans_no_connections_no_problems():
    text = md(simple())
    assert "Nobody reviews anything" in section(text, "People in the loop")
    assert "Nothing outside the workflow itself." in section(text, "What it connects to")
    assert "found no problems" in section(text, "Things to check")


def test_findings_come_with_suggestions():
    wf = Workflow(nodes=[N("s", NodeType.START), N("a", NodeType.API, "Fetch", config={"method": "GET", "url": "u"}), N("e", NodeType.END)],
                  edges=[E("s", "a"), E("a", "e")])
    checks = section(md(wf), "Things to check")
    assert "no failure branch" in checks and "*Suggestion:*" in checks


def test_estimates_are_labelled_rough_and_cover_a_range():
    wf = Workflow(nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}), N("h", NodeType.HITL), N("l", NodeType.LLM),
                         N("e1", NodeType.END, "E1"), N("e2", NodeType.END, "E2")],
                  edges=[E("s", "c"), E("c", "h", "a"), E("c", "l", "b"), E("h", "e1"), E("l", "e2")])
    text = md(wf)
    assert "| Possible routes | 2 |" in text
    assert "| Rough time per run | 2 s – 5 min" in text
    assert "rough estimates" in text


def test_duration_formatting():
    assert _duration(5) == "5 ms" and _duration(4705) == "4.7 s" and _duration(2000) == "2 s"
    assert _duration(90_000) == "1.5 min" and _duration(900_000) == "15 min"


# ── Untrusted text cannot break the document ─────────────────────────────────

def test_user_text_cannot_break_tables_code_or_headings():
    nasty = "evil | `code`\n## Injected heading\n| fake | row |"
    wf = Workflow(
        name="Name\n# Not a heading",
        description="line one\n\n# Also not a heading",
        nodes=[N("s", NodeType.START), N("a", NodeType.API, "Call | **bold**", config={"method": "GET", "url": nasty}),
               N("d", NodeType.DATABASE, "DB", config={"query": nasty}), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "d"), E("d", "e")],
    )
    text = md(wf)
    assert len(re.findall(r"^# ", text, re.M)) == 1                    # name and description collapsed to single lines
    assert not re.search(r"^## Injected", text, re.M)
    for row in section(text, "What it connects to").splitlines():
        if row.startswith("| ") and "---" not in row and "Step |" not in row:
            assert len(re.split(r"(?<!\\)\|", row)) == 6               # 4 cells, whatever the content
    assert "`code`" not in text and "'code'" in text                    # backticks inside inline code are neutralised


def test_long_text_is_truncated():
    wf = Workflow(nodes=[N("s", NodeType.START), N("l", NodeType.LLM, "L", config={"prompt": "word " * 500}), N("e", NodeType.END)],
                  edges=[E("s", "l"), E("l", "e")])
    line = next(l for l in md(wf).splitlines() if "Instruction:" in l)
    assert len(line) < 260 and "…" in line


# ── Endpoint ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_explain_endpoint_returns_markdown_without_touching_usage():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/explain", json={"workflow": simple().model_dump(mode="json")})
    assert res.status_code == 200
    assert res.json()["markdown"].startswith("# Greeter")


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_explain_endpoint_rejects_oversized_workflows():
    nodes = [{"id": f"n{i}", "type": "TRANSFORM", "name": "N"} for i in range(101)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/explain", json={"workflow": {"nodes": nodes}})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_explain_endpoint_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/explain", json={"workflow": simple().model_dump(mode="json")})
    assert res.status_code in (401, 403)

"""Tests for request/workflow size limits (Task 38)."""
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.body_limit import BodySizeLimitMiddleware
from app.main import app
from app.models import workflow as wfm
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode

pytestmark = pytest.mark.usefixtures("override_approved_user")

BASE = "http://test"


def _nodes(n):
    return [WorkflowNode(id=f"n{i}", type=NodeType.TRANSFORM, name=f"N{i}") for i in range(n)]


# ── Model limits ─────────────────────────────────────────────────────────────

def test_max_nodes_allowed_and_exceeded():
    Workflow(nodes=_nodes(wfm.MAX_NODES))
    with pytest.raises(ValidationError):
        Workflow(nodes=_nodes(wfm.MAX_NODES + 1))


def test_max_edges_exceeded():
    edges = [WorkflowEdge(source="a", target="b") for _ in range(wfm.MAX_EDGES + 1)]
    with pytest.raises(ValidationError):
        Workflow(edges=edges)


def test_config_size_cap():
    with pytest.raises(ValidationError):
        WorkflowNode(type=NodeType.LLM, name="X", config={"prompt": "x" * (wfm.MAX_DICT_JSON_BYTES + 1)})
    WorkflowNode(type=NodeType.LLM, name="X", config={"prompt": "x" * 1000})


def test_metadata_and_name_caps():
    with pytest.raises(ValidationError):
        Workflow(metadata={"blob": "x" * (wfm.MAX_DICT_JSON_BYTES + 1)})
    with pytest.raises(ValidationError):
        WorkflowEdge(source="a", target="b", metadata={"blob": "x" * (wfm.MAX_DICT_JSON_BYTES + 1)})
    with pytest.raises(ValidationError):
        Workflow(name="n" * (wfm.MAX_NAME_LENGTH + 1))
    with pytest.raises(ValidationError):
        WorkflowNode(type=NodeType.LLM, name="n" * (wfm.MAX_NAME_LENGTH + 1))


# ── API behaviour ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("path,wrap", [
    ("/api/workflows/validate", lambda w: {"workflow": w}),
    ("/api/workflows/simulate", lambda w: {"workflow": w, "input": {}}),
])
async def test_too_many_nodes_returns_422(path, wrap):
    payload = {"nodes": [{"id": f"n{i}", "type": "TRANSFORM", "name": "N"} for i in range(wfm.MAX_NODES + 1)]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post(path, json=wrap(payload))
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_oversized_body_returns_413_via_content_length():
    big = {"workflow": {"description": "x" * 2_000_000}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/validate", json=big)
    assert res.status_code == 413
    assert "too large" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_chunked_body_over_limit_returns_413():
    async def ok_app(scope, receive, send):
        while True:
            msg = await receive()
            if not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = BodySizeLimitMiddleware(ok_app, max_bytes=100)
    sent = []

    chunks = [{"type": "http.request", "body": b"x" * 60, "more_body": True},
              {"type": "http.request", "body": b"x" * 60, "more_body": False}]

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    await mw({"type": "http", "headers": []}, receive, send)
    assert sent[0]["status"] == 413

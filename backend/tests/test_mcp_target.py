"""The MCP export target and the multi-target endpoint (Task 56)."""
import ast
import io
import json
import re
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow
from app.services.exporters import TARGETS, export_zip
from app.services.langgraph_exporter import ExportError
from app.services.mcp_exporter import McpExporter
from tests.test_langgraph_exporter import E, N, routed_workflow, run_generated_tests, write_project

BASE = "http://test"


def tools_workflow() -> Workflow:
    """A tool server: no START/END needed, some steps are not tools."""
    return Workflow(
        id="wf-tools", name="Support Tools", description="Things support agents can do.",
        nodes=[
            N("fetch-customer", NodeType.API, "Fetch customer", config={"method": "GET", "url": "https://api.test/customers/{{customerId}}", "headers": {"Authorization": "env:API_TOKEN"}}),
            N("create-ticket", NodeType.API, "Create ticket", config={"method": "POST", "url": "https://api.test/tickets", "requestSchema": {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "integer"}}}}),
            N("orders", NodeType.DATABASE, "Recent orders", config={"connection": "env:DB_URL", "query": "SELECT * FROM orders WHERE customer = {{customerId}} AND status = {{status}}"}),
            N("kb", NodeType.RAG, "Policies", config={"knowledgeBase": "policies"}),
            N("kb2", NodeType.RAG, "Templated search", config={"knowledgeBase": "policies", "query": "{{topic}} policy"}),
            N("declared", NodeType.TOOL, "Escalate", config={"name": "escalate", "description": "Page the on-call manager"},
              input_schema={"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}),
            N("free", NodeType.TOOL, "Anything", config={"name": "anything"}),
            N("llm", NodeType.LLM, "Not a tool"), N("cond", NodeType.CONDITION, "Also not"), N("tf", NodeType.TRANSFORM, "Nor this"),
        ],
        edges=[],
    )


def export(wf=None):
    return McpExporter().export(wf or tools_workflow())


def tools(files):
    return {t["name"]: t for t in json.loads(files["tools.json"])["tools"]}


# ── Definitions ──────────────────────────────────────────────────────────────

def test_only_tool_api_database_and_rag_steps_become_tools():
    files = export()
    assert set(tools(files)) == {"fetch_customer", "create_ticket", "orders", "kb", "kb2", "declared", "free"}
    assert json.loads(files["tools.json"])["server"] == "support-tools"


def test_input_schemas_come_from_contracts_then_placeholders_then_requests():
    t = tools(export())
    assert t["declared"]["inputSchema"] == {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}
    assert t["fetch_customer"]["inputSchema"] == {"type": "object", "properties": {"customerId": {}}, "required": ["customerId"]}
    assert t["orders"]["inputSchema"]["required"] == ["customerId", "status"]                  # in order of first use
    assert set(t["create_ticket"]["inputSchema"]["properties"]) == {"title", "priority"}
    assert t["create_ticket"]["inputSchema"]["properties"]["priority"] == {"type": "integer"}
    assert t["kb"]["inputSchema"]["properties"]["query"]["type"] == "string" and t["kb"]["inputSchema"]["required"] == ["query"]
    assert t["kb2"]["inputSchema"]["required"] == ["topic"]                                     # the query template decides
    assert t["free"]["inputSchema"] == {"type": "object", "properties": {}, "additionalProperties": True}


def test_descriptions_say_what_the_tool_does_and_whether_it_writes():
    t = tools(export())
    assert t["declared"]["description"] == "Page the on-call manager"
    assert "GET https://api.test/customers/{{customerId}} (reads data)" in t["fetch_customer"]["description"]
    assert "POST" in t["create_ticket"]["description"] and "(changes data)" in t["create_ticket"]["description"]
    assert "reads data" in t["orders"]["description"] and "'policies'" in t["kb"]["description"]
    assert all(len(d["description"]) <= 300 and "\n" not in d["description"] for d in t.values())


def test_every_tool_points_at_a_real_function():
    files = export()
    for tool in tools(files).values():
        assert f"def {tool['function']}(" in files["integrations.py"]
    assert "import connectors" in files["integrations.py"] and "connectors.py" in files


def test_a_workflow_without_tool_steps_is_refused_with_the_reason():
    with pytest.raises(ExportError, match="nothing to expose as an MCP tool"):
        McpExporter().export(routed_workflow())


def test_no_start_or_end_is_needed_and_unconnected_tools_are_included():
    wf = Workflow(nodes=[N("lonely", NodeType.TOOL, "Lonely tool", config={"name": "lonely"})], edges=[])
    assert set(tools(McpExporter().export(wf))) == {"lonely"}


def test_names_are_unique_and_valid_for_mcp():
    wf = Workflow(nodes=[N("a-b", NodeType.TOOL), N("a_b", NodeType.TOOL), N("a b", NodeType.TOOL), N("class", NodeType.TOOL), N("data", NodeType.TOOL)], edges=[])
    names = list(tools(McpExporter().export(wf)))
    assert len(names) == len(set(names)) == 5
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n) for n in names)


# ── The project ──────────────────────────────────────────────────────────────

def test_files_and_requirements_follow_the_tools_used():
    files = export()
    assert {"server.py", "tools.json", "integrations.py", "connectors.py", "runtime.py", "workflow.json", "tests/test_tools.py", "README.md"} <= set(files)
    req = files["requirements.txt"]
    assert "mcp>=1.2,<2" in req and "httpx" in req and "sqlalchemy" in req and "langchain-openai" in req and "langgraph" not in req
    only_tool = McpExporter().export(Workflow(nodes=[N("t", NodeType.TOOL)], edges=[]))
    assert "httpx" not in only_tool["requirements.txt"] and "connectors.py" not in only_tool
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text, filename=name)


def test_env_and_readme_guide_the_user():
    files = export()
    assert "API_TOKEN=" in files[".env.example"] and "DB_URL=" in files[".env.example"]
    readme = files["README.md"]
    assert "| `fetch_customer` | API “Fetch customer” |" in readme
    snippet = re.search(r"```json\n(.*?)\n```", readme, re.S).group(1)
    config = json.loads(snippet)
    assert config["mcpServers"]["support-tools"]["command"] == "python"
    assert "AIFLOW_MOCK" in snippet


def test_zip_is_named_for_the_target_and_reproducible():
    folder, data = export_zip(tools_workflow(), "mcp")
    assert folder == "support-tools-mcp"
    assert export_zip(tools_workflow(), "mcp") == (folder, data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "support-tools-mcp/server.py" in z.namelist()


def test_generated_tests_pass_in_a_clean_environment(tmp_path):
    result = run_generated_tests(write_project(export(), tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\d+ passed", result.stdout)          # 7 definitions + 7 mock calls (+ the server test when `mcp` is installed)


def test_hostile_text_cannot_become_code(tmp_path):
    evil = '"""\nimport os; open("PWNED", "w").write("x")\n#'
    wf = Workflow(name=evil, description=evil, nodes=[
        N("t", NodeType.TOOL, evil, config={"name": evil, "description": evil}),
        N("a", NodeType.API, evil, config={"method": evil, "url": evil + "{{x}}"}),
    ], edges=[])
    files = McpExporter().export(wf)
    for name, text in files.items():
        if name.endswith(".py"):
            tree = ast.parse(text)
            calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            assert "open" not in calls or name in ("runtime.py", "connectors.py", "server.py", "aiflow_schema.py", "aiflow_expressions.py"), name
    json.loads(files["tools.json"])                                              # still valid JSON
    project = write_project(files, tmp_path)
    assert run_generated_tests(project).returncode == 0
    assert not (project / "PWNED").exists()


# ── Dispatcher and endpoint ──────────────────────────────────────────────────

def test_dispatcher_knows_every_target_and_rejects_others():
    assert set(TARGETS) == {"langgraph", "python", "mcp"}
    assert [export_zip(routed_workflow(), t)[0] for t in ("langgraph", "python")] == ["router-langgraph", "router-python"]
    with pytest.raises(ExportError, match="Unknown export target 'cobol'"):
        export_zip(routed_workflow(), "cobol")


async def post(path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        return await client.post(path, json=body)


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
@pytest.mark.parametrize("target,wf,folder,marker", [
    ("langgraph", routed_workflow, "router-langgraph", "graph.py"),
    ("python", routed_workflow, "router-python", "engine.py"),
    ("mcp", tools_workflow, "support-tools-mcp", "server.py"),
])
async def test_endpoint_returns_the_chosen_target(target, wf, folder, marker):
    res = await post("/api/workflows/export", {"workflow": wf().model_dump(mode="json"), "target": target})
    assert res.status_code == 200 and res.headers["content-disposition"] == f'attachment; filename="{folder}.zip"'
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert f"{folder}/{marker}" in z.namelist()


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_defaults_to_langgraph_and_keeps_the_old_path():
    wf = routed_workflow().model_dump(mode="json")
    assert (await post("/api/workflows/export", {"workflow": wf})).headers["content-disposition"].endswith('router-langgraph.zip"')
    old = await post("/api/workflows/export/langgraph", {"workflow": wf, "target": "mcp"})      # the old path ignores `target`
    assert old.headers["content-disposition"].endswith('router-langgraph.zip"')


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_errors():
    wf = routed_workflow().model_dump(mode="json")
    assert (await post("/api/workflows/export", {"workflow": wf, "target": "cobol"})).status_code == 422
    res = await post("/api/workflows/export", {"workflow": routed_workflow().model_dump(mode="json"), "target": "mcp"})
    assert res.status_code == 422 and "nothing to expose" in res.json()["detail"]
    suite = {"id": "5b0c1f5e-0000-4000-8000-000000000001", "workflow_id": "wf-routed", "cases": []}
    with patch("app.api.export_routes.db.get_suite", new_callable=AsyncMock, return_value=suite) as get:
        res = await post("/api/workflows/export", {"workflow": tools_workflow().model_dump(mode="json"), "target": "mcp", "suite_id": suite["id"]})
    assert res.status_code == 422 and "do not include tests" in res.json()["detail"]
    get.assert_not_awaited()                                                      # refused before touching the database


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_targets_listing():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.get("/api/workflows/export/targets")
    assert res.status_code == 200
    targets = {t["id"]: t for t in res.json()["targets"]}
    assert set(targets) == {"langgraph", "python", "mcp"}
    assert targets["mcp"]["supports_tests"] is False and targets["python"]["supports_tests"] is True


@pytest.mark.asyncio
async def test_new_endpoints_require_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        assert (await client.get("/api/workflows/export/targets")).status_code in (401, 403)
        assert (await client.post("/api/workflows/export", json={"workflow": routed_workflow().model_dump(mode="json")})).status_code in (401, 403)

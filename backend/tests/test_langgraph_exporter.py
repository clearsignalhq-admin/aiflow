"""Tests for the LangGraph exporter (Task 53).

Most of these write the generated project to disk and run it in a separate Python process with its own
pytest, so they prove the export works as a standalone project (not just that the text looks right).
"""
import ast
import asyncio
import glob
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.services.langgraph_exporter import DIFFERENCES, ExportError, LangGraphExporter
from app.services.suite_runner import run_case
from tests.conftest import APPROVED_USER

BASE = "http://test"
EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(s, t, c=None):
    return WorkflowEdge(source=s, target=t, condition=c)


def load(path: str) -> Workflow:
    return Workflow(**json.load(open(os.path.join(EXAMPLES, path), encoding="utf-8")))


def write_project(files: dict[str, str], root: Path) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def run_py(project: Path, *args: str, timeout: int = 120, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run Python in the generated project with a clean environment (no AiFlow/OpenAI settings leak in)."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("AIFLOW_", "PYTHON", "OPENAI"))}
    clean["PYTHONIOENCODING"] = "utf-8"
    clean.update(env or {})
    return subprocess.run([sys.executable, *args], cwd=project, env=clean, capture_output=True, text=True, timeout=timeout, encoding="utf-8")


def run_generated_tests(project: Path) -> subprocess.CompletedProcess:
    return run_py(project, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore")


def routed_workflow() -> Workflow:
    """START → LLM(tier: basic|premium) → CONDITION → premium | basic → END  — branches vary with the seed."""
    return Workflow(
        id="wf-routed", name="Router",
        nodes=[
            N("s", NodeType.START, "Start"),
            N("l", NodeType.LLM, "Classify", config={"prompt": "Classify {{message}}"},
              output_schema={"type": "object", "properties": {"tier": {"type": "string", "enum": ["basic", "premium"]}}}),
            N("c", NodeType.CONDITION, "Route", config={"expression": "input.tier"}),
            N("p", NodeType.TRANSFORM, "Premium path"), N("b", NodeType.TRANSFORM, "Basic path"), N("e", NodeType.END, "End"),
        ],
        edges=[E("s", "l"), E("l", "c"), E("c", "p", "premium"), E("c", "b", "basic"), E("p", "e"), E("b", "e")],
        metadata={"sample_input": {"message": "hello"}},
    )


# ── Shape of the export ──────────────────────────────────────────────────────

def test_files_in_the_project():
    files = LangGraphExporter().export(routed_workflow())
    assert set(files) == {
        "workflow.json", "state.py", "runtime.py", "aiflow_expressions.py", "aiflow_schema.py", "nodes.py", "integrations.py",
        "routing.py", "graph.py", "main.py", "requirements.txt", ".env.example", "pytest.ini", "README.md",
        "tests/aiflow_assertions.py", "tests/cases.json", "tests/test_workflow.py",
    }
    assert json.loads(files["workflow.json"])["id"] == "wf-routed"             # the workflow is shipped as the source of truth
    assert json.loads(files["tests/cases.json"]) == []


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(EXAMPLES, "**", "*.json"), recursive=True)))
def test_every_example_exports_to_valid_python(path):
    wf = Workflow(**json.load(open(path, encoding="utf-8")))
    files = LangGraphExporter().export(wf)
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text, filename=name)                                       # raises on a syntax error
    assert "langgraph" in files["requirements.txt"]


def test_export_is_deterministic_and_the_zip_is_reproducible():
    wf = load("medium/customer-support.json")
    assert LangGraphExporter().export(wf) == LangGraphExporter().export(wf)
    folder1, zip1 = LangGraphExporter().export_zip(wf)
    folder2, zip2 = LangGraphExporter().export_zip(wf)
    assert folder1 == folder2 == "customer-support-agent-langgraph" and zip1 == zip2
    with zipfile.ZipFile(io.BytesIO(zip1)) as z:
        assert all(n.startswith(f"{folder1}/") for n in z.namelist()) and z.testzip() is None
        assert f"{folder1}/graph.py" in z.namelist()


def test_graph_mirrors_the_workflow():
    files = LangGraphExporter().export(routed_workflow())
    graph = files["graph.py"]
    assert "graph.add_edge(START, 's')" in graph
    assert "graph.add_edge('s', 'l')" in graph and "graph.add_edge('p', 'e')" in graph and "graph.add_edge('e', END)" in graph
    assert "graph.add_conditional_edges('c', routing.route_c)" in graph
    assert "graph.add_edge('c'" not in graph                                      # branches go through the router
    assert "BRANCHES_C = [('premium', 'p'), ('basic', 'b')]" in files["routing.py"]


def test_parallel_branches_and_duplicate_edges():
    wf = Workflow(nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM), N("b", NodeType.TRANSFORM), N("e", NodeType.END)],
                  edges=[E("s", "a"), E("s", "a"), E("s", "b"), E("a", "e"), E("b", "e")])
    graph = LangGraphExporter().export(wf)["graph.py"]
    assert graph.count("graph.add_edge('s', 'a')") == 1 and "graph.add_edge('s', 'b')" in graph


def test_unreachable_steps_are_left_out_and_reported():
    wf = Workflow(nodes=[N("s", NodeType.START), N("e", NodeType.END), N("orphan", NodeType.LLM, "Lonely step")], edges=[E("s", "e")])
    files = LangGraphExporter().export(wf)
    assert "orphan" not in files["graph.py"] and "orphan" not in files["nodes.py"]
    assert "Steps not connected to START were left out: Lonely step" in files["README.md"]
    assert "orphan" in files["workflow.json"]                                    # still in the shipped source of truth


@pytest.mark.parametrize("nodes,edges,message", [
    ([N("e", NodeType.END)], [], "exactly one START"),
    ([N("s", NodeType.START), N("s2", NodeType.START), N("e", NodeType.END)], [E("s", "e")], "exactly one START"),
    ([N("s", NodeType.START)], [], "at least one END"),
    ([], [], "exactly one START"),
])
def test_unexportable_workflows(nodes, edges, message):
    with pytest.raises(ExportError, match=message):
        LangGraphExporter().export(Workflow(nodes=nodes, edges=edges))


def test_names_are_made_safe_and_unique():
    wf = Workflow(
        nodes=[N("start", NodeType.START), N("data", NodeType.TRANSFORM), N("class", NodeType.TRANSFORM), N("123", NodeType.TRANSFORM),
               N("a-b", NodeType.TRANSFORM), N("a_b", NodeType.TRANSFORM), N("a b", NodeType.TRANSFORM), N("end", NodeType.END)],
        edges=[E("start", "data"), E("data", "class"), E("class", "123"), E("123", "a-b"), E("a-b", "a_b"), E("a_b", "a b"), E("a b", "end")],
    )
    graph = LangGraphExporter().export(wf)["graph.py"]
    ast.parse(graph)
    names = [line.split("'")[1] for line in graph.splitlines() if "add_node(" in line]
    assert len(names) == len(set(names)) == 8
    assert not {"data", "visited", "result", "class"} & set(names)               # state keys and keywords are avoided
    assert all(n.isidentifier() for n in names)


def test_assertion_engine_is_adapted_for_standalone_use():
    src = LangGraphExporter().export(routed_workflow())["tests/aiflow_assertions.py"]
    assert "app.services" not in src and "pydantic" not in src
    assert "import aiflow_expressions as expressions" in src and "@dataclass\nclass AssertionResult" in src
    ast.parse(src)


# ── The generated project really runs ────────────────────────────────────────

def test_generated_project_runs_its_own_tests(tmp_path):
    cases = [{"name": "any input", "input": {"message": "hi"}, "assertions": [{"type": "max_steps", "max_steps": 10}], "seed": None}]
    project = write_project(LangGraphExporter().export(routed_workflow(), cases), tmp_path)
    result = run_generated_tests(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_exported_code_takes_the_same_branches_as_the_simulator(tmp_path):
    """The suite replays with the same seeds: if the exported graph chose differently, a test would fail."""
    wf = routed_workflow()
    cases = []
    for i in range(10):
        sim = asyncio.run(run_case(wf, {"id": f"c{i}", "name": f"seed {i}", "input": {"message": "hi"}, "assertions": [], "seed": None}, i, 0))
        assert sim.status == "passed"
        visited = set(sim.path)
        assertions = [{"type": "visits_node" if n.id in visited else "skips_node", "node_id": n.id} for n in wf.nodes]
        cases.append({"name": f"seed {i}", "input": {"message": "hi"}, "assertions": assertions, "seed": None})
    taken = {("p" in {a["node_id"] for a in c["assertions"] if a["type"] == "visits_node"}) for c in cases}
    assert taken == {True, False}                                                # the seeds really do exercise both branches

    project = write_project(LangGraphExporter().export(wf, cases, run_seed=0), tmp_path)
    result = run_generated_tests(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 passed" in result.stdout


def test_a_failing_check_fails_the_generated_test_with_a_reason(tmp_path):
    cases = [{"name": "wrong", "input": {}, "assertions": [{"type": "equals", "path": "tier", "value": "gold", "label": "tier is gold"}], "seed": 0}]
    project = write_project(LangGraphExporter().export(routed_workflow(), cases), tmp_path)
    result = run_generated_tests(project)
    assert result.returncode != 0
    assert "tier is gold" in result.stdout and "expected 'gold'" in result.stdout


def test_pinned_mock_output_is_used_in_mock_mode(tmp_path):
    wf = routed_workflow()
    wf.nodes[1].config["mock_output"] = {"tier": "premium"}
    cases = [{"name": f"c{i}", "input": {}, "assertions": [{"type": "equals", "path": "tier", "value": "premium"},
                                                         {"type": "visits_node", "node_id": "p"}], "seed": i} for i in range(3)]
    result = run_generated_tests(write_project(LangGraphExporter().export(wf, cases), tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_runs_in_mock_mode_and_prints_the_result(tmp_path):
    project = write_project(LangGraphExporter().export(routed_workflow()), tmp_path)
    result = run_py(project, "main.py", "--mock", "--seed", "3", "--input", '{"message": "hello"}')
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["message"] == "hello" and out["tier"] in ("basic", "premium")
    same = run_py(project, "main.py", "--mock", "--seed", "3", "--input", '{"message": "hello"}')
    assert same.stdout == result.stdout                                           # reproducible


def test_human_review_pauses_and_resumes(tmp_path):
    wf = Workflow(
        id="w", name="Review",
        nodes=[N("s", NodeType.START), N("h", NodeType.HITL, "Manager approval", config={"instructions": "Check the amount"}), N("e", NodeType.END)],
        edges=[E("s", "h"), E("h", "e")],
    )
    project = write_project(LangGraphExporter().export(wf), tmp_path)
    auto = run_py(project, "main.py", "--mock", "--auto-approve", "--input", '{"amount": 5}')
    assert auto.returncode == 0, auto.stderr
    assert json.loads(auto.stdout) == {"amount": 5, "approved": True, "decision": "approve"}
    assert "Check the amount" in auto.stderr and "Manager approval" in auto.stderr

    asked = subprocess.run([sys.executable, "main.py", "--mock", "--input", '{"amount": 5}'], cwd=project, input="reject\n",
                           capture_output=True, text=True, timeout=120, encoding="utf-8",
                           env={k: v for k, v in os.environ.items() if not k.startswith(("AIFLOW_", "PYTHON"))})
    assert json.loads(asked.stdout)["approved"] is False


def test_a_decision_with_no_matching_branch_fails_loudly(tmp_path):
    wf = Workflow(
        id="w", name="Bad labels",
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Decide", config={"expression": "input.amount > 5"}),
               N("a", NodeType.END, "A"), N("b", NodeType.END, "B")],
        edges=[E("s", "c"), E("c", "a", "positive"), E("c", "b", "negative")],
    )
    project = write_project(LangGraphExporter().export(wf), tmp_path)
    result = run_py(project, "main.py", "--mock", "--input", '{"amount": 9}')
    assert result.returncode != 0
    assert "matches none of its branches (negative, positive)" in result.stderr


def test_default_branch_and_missing_expression(tmp_path):
    wf = Workflow(
        id="w", name="Defaults",
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Decide", config={"expression": "input.kind"}),
               N("a", NodeType.TRANSFORM, "A"), N("o", NodeType.TRANSFORM, "Other"), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "a", "alpha"), E("c", "o", "else"), E("a", "e"), E("o", "e")],
    )
    project = write_project(LangGraphExporter().export(wf), tmp_path)
    out = json.loads(run_py(project, "main.py", "--mock", "--input", '{"kind": "zzz"}').stdout)
    assert out["kind"] == "zzz" and out["_transformed"] is True
    sim = json.loads(run_py(project, "main.py", "--mock", "--seed", "1", "--input", '{"kind": "alpha"}').stdout)
    assert sim["kind"] == "alpha"


def test_mock_mode_returns_fixtures_for_every_integration_and_only_unimplementable_steps_are_todo(tmp_path):
    wf = Workflow(
        id="w", name="Stubs",
        nodes=[N("s", NodeType.START), N("api", NodeType.API, "Notify", config={"method": "POST", "url": "https://x.test"}),
               N("db", NodeType.DATABASE, "Save", config={"query": "INSERT INTO t VALUES (1)", "connection": "env:DB_URL"}),
               N("rag", NodeType.RAG, "Docs", config={"knowledgeBase": "kb"}), N("tool", NodeType.TOOL, "Search", config={"name": "web"}),
               N("t", NodeType.TRANSFORM, "Tidy"), N("e", NodeType.END)],
        edges=[E("s", "api"), E("api", "db"), E("db", "rag"), E("rag", "tool"), E("tool", "t"), E("t", "e")],
    )
    files = LangGraphExporter().export(wf)
    for stub in ("api_api", "database_db", "rag_rag", "tool_tool", "transform_t"):
        assert f"def {stub}(" in files["integrations.py"]
    readme = files["README.md"]
    todo = readme.split("## What you still need to implement")[1]
    assert "`tool_tool`" in todo and "`transform_t`" in todo
    assert "`api_api`" not in todo and "`database_db`" not in todo and "`rag_rag`" not in todo     # these really run
    assert "What runs for real" in readme and "bound parameters" in readme
    assert "changes data in another system" in files["integrations.py"]

    project = write_project(files, tmp_path)
    out = json.loads(run_py(project, "main.py", "--mock", "--input", "{}").stdout)
    assert out["status"] == 200 and out["rows"] == [] and out["context"] == "" and out["tool"] == "Search"

    unmocked = run_py(project, "main.py", "--input", "{}", env={"DB_URL": "sqlite://"})
    assert unmocked.returncode != 0                                  # the first step makes a real request to https://x.test


@pytest.mark.parametrize("types,expected,absent", [
    ([NodeType.API], ["httpx"], ["sqlalchemy"]),
    ([NodeType.DATABASE], ["sqlalchemy", "add the driver"], ["httpx"]),
    ([NodeType.RAG], [], ["httpx", "sqlalchemy"]),
    ([], [], ["httpx", "sqlalchemy"]),
])
def test_requirements_and_connectors_follow_the_steps_used(types, expected, absent):
    nodes = [N("s", NodeType.START)] + [N(f"x{i}", t, config={"method": "GET", "url": "http://x", "query": "SELECT 1", "knowledgeBase": "k"})
                                         for i, t in enumerate(types)] + [N("e", NodeType.END)]
    ids = [n.id for n in nodes]
    wf = Workflow(nodes=nodes, edges=[E(a, b) for a, b in zip(ids, ids[1:])])
    files = LangGraphExporter().export(wf)
    for word in expected:
        assert word in files["requirements.txt"]
    for word in absent:
        assert word not in files["requirements.txt"]
    assert ("connectors.py" in files) == bool(types)


def test_env_names_from_the_workflow_are_listed_for_the_user():
    wf = Workflow(
        nodes=[N("s", NodeType.START),
               N("a", NodeType.API, config={"method": "GET", "url": "http://x", "headers": {"Authorization": "env:SERVICE_TOKEN", "Accept": "json"}}),
               N("d", NodeType.DATABASE, config={"query": "SELECT 1", "connection": "env:ORDERS_DB"}), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "d"), E("d", "e")],
    )
    env = LangGraphExporter().export(wf)[".env.example"]
    assert "SERVICE_TOKEN=" in env and "ORDERS_DB=" in env and "Accept" not in env


def test_schema_driven_fixtures_equal_the_simulators(tmp_path):
    """The exported mock data is generated by the same code and seed as the simulator's."""
    wf = routed_workflow()
    seed = 7
    sim = asyncio.run(run_case(wf, {"id": "c", "name": "c", "input": {}, "assertions": [], "seed": seed}, 0, 0))
    project = write_project(LangGraphExporter().export(wf), tmp_path)
    out = json.loads(run_py(project, "main.py", "--mock", "--seed", str(seed), "--input", "{}").stdout)
    assert out["tier"] == sim.output["tier"]


# ── Untrusted text can never become code ─────────────────────────────────────

def test_hostile_text_is_data_not_code(tmp_path):
    evil = '"""\nimport os; open("PWNED", "w").write("x")\n#'
    wf = Workflow(
        id="w", name=evil, description=evil,
        nodes=[N("s", NodeType.START, evil), N("l", NodeType.LLM, evil, config={"prompt": evil, "model": evil}),
               N("a", NodeType.API, evil, config={"method": evil, "url": evil}),
               N("c", NodeType.CONDITION, evil, config={"expression": "true"}),
               N("t", NodeType.TOOL, evil, config={"name": evil, "description": evil}),
               N("e", NodeType.END, evil)],
        edges=[E("s", "l"), E("l", "a"), E("a", "c"), E("c", "t", "true"), E("c", "e", evil), E("t", "e")],
        metadata={"sample_input": {"k": evil}},
    )
    files = LangGraphExporter().export(wf)
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text, filename=name)
    # Names may appear inside docstrings (sanitised to one line), but never as executable code:
    for name in ("nodes.py", "integrations.py", "routing.py", "graph.py"):
        tree = ast.parse(files[name])
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        assert "open" not in calls and "os" not in imports, name
    # Edge labels are matched exactly, so they are kept verbatim, but only as string data in a list:
    assert "BRANCHES_C = [(" in files["routing.py"]
    project = write_project(files, tmp_path)
    assert run_generated_tests(project).returncode == 0
    run_py(project, "main.py", "--mock", "--input", "{}")
    assert not (project / "PWNED").exists()


# ── Endpoint ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_returns_a_zip():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/export/langgraph", json={"workflow": routed_workflow().model_dump(mode="json")})
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert res.headers["content-disposition"] == 'attachment; filename="router-langgraph.zip"'
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert "router-langgraph/graph.py" in z.namelist()
        assert json.loads(z.read("router-langgraph/tests/cases.json")) == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_includes_the_users_suite_cases():
    suite = {"id": "5b0c1f5e-0000-4000-8000-000000000001", "workflow_id": "wf-routed", "cases": [
        {"id": "c1", "name": "one", "input": {"a": 1}, "assertions": [{"type": "max_steps", "max_steps": 9}], "seed": 4, "tags": []}]}
    with patch("app.api.export_routes.db.get_suite", new_callable=AsyncMock, return_value=suite) as get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.post("/api/workflows/export/langgraph", json={
                "workflow": routed_workflow().model_dump(mode="json"), "suite_id": suite["id"], "seed": 5})
    assert res.status_code == 200
    assert get.await_args.args == (APPROVED_USER.id, suite["id"])                # scoped to the caller
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        cases = json.loads(z.read("router-langgraph/tests/cases.json"))
        assert cases == [{"name": "one", "input": {"a": 1}, "assertions": [{"type": "max_steps", "max_steps": 9}], "seed": 4}]
        assert "RUN_SEED = 5" in z.read("router-langgraph/tests/test_workflow.py").decode()


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
@pytest.mark.parametrize("suite_id,suite,status", [
    ("not-a-uuid", None, 404),
    ("5b0c1f5e-0000-4000-8000-000000000002", None, 404),
    ("5b0c1f5e-0000-4000-8000-000000000003", {"id": "x", "workflow_id": "another", "cases": []}, 422),
])
async def test_endpoint_suite_errors(suite_id, suite, status):
    with patch("app.api.export_routes.db.get_suite", new_callable=AsyncMock, return_value=suite):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.post("/api/workflows/export/langgraph", json={
                "workflow": routed_workflow().model_dump(mode="json"), "suite_id": suite_id})
    assert res.status_code == status


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_endpoint_rejects_an_unexportable_workflow_with_the_reason():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/export/langgraph", json={"workflow": {"nodes": [], "edges": []}})
    assert res.status_code == 422 and "exactly one START" in res.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/export/langgraph", json={"workflow": routed_workflow().model_dump(mode="json")})
    assert res.status_code in (401, 403)


def test_documented_differences_are_in_the_readme():
    readme = LangGraphExporter().export(routed_workflow())["README.md"]
    for line in DIFFERENCES:
        assert line in readme

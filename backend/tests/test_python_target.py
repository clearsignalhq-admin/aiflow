"""The plain-Python export target (Task 56): no framework, `engine.py` is the whole runtime."""
import ast
import asyncio
import glob
import json
import os
import subprocess
import sys
import zipfile
import io

import pytest

from app.models.workflow import NodeType, Workflow
from app.services.langgraph_exporter import ExportError, LangGraphExporter
from app.services.suite_runner import run_case
from tests.test_langgraph_connectors import server, workflow as chain  # noqa: F401  (fixture + helper)
from tests.test_langgraph_exporter import E, N, load, routed_workflow, run_generated_tests, run_py, write_project


def export(wf, cases=None, seed=0):
    return LangGraphExporter().export(wf, cases, seed, target="python")


def test_project_has_no_framework_dependency():
    files = export(routed_workflow())
    assert {"engine.py", "review.py", "state.py", "graph.py", "nodes.py", "main.py"} <= set(files)
    for name, text in files.items():
        if name.endswith((".py", ".txt")):
            assert "langgraph" not in text.lower(), name
    assert "langgraph" not in files["requirements.txt"] and "pytest" in files["requirements.txt"]
    assert "from review import interrupt" in files["nodes.py"]
    assert "plain Python project" in files["README.md"]


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "examples", "**", "*.json"), recursive=True)))
def test_every_example_exports_to_valid_python(path):
    files = export(Workflow(**json.load(open(path, encoding="utf-8"))))
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text, filename=name)


def test_graph_is_plain_data():
    graph = export(routed_workflow())["graph.py"]
    assert "ENTRY = 's'" in graph and "'c': routing.route_c" in graph
    assert "'s': ['l']" in graph and "'p': ['e']" in graph
    assert "'c':" not in graph.split("EDGES =")[1].split("ROUTERS")[0]        # decisions are not in the plain edge table


def test_unknown_target_and_unexportable_workflows_are_refused():
    with pytest.raises(ExportError, match="Unknown export target"):
        LangGraphExporter().export(routed_workflow(), target="cobol")
    with pytest.raises(ExportError, match="exactly one START"):
        export(Workflow(nodes=[], edges=[]))


def test_zip_folder_is_named_for_the_target():
    folder, data = LangGraphExporter().export_zip(routed_workflow(), target="python")
    assert folder == "router-python"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "router-python/engine.py" in z.namelist()
    assert LangGraphExporter().export_zip(routed_workflow(), target="python") == (folder, data)       # reproducible


def test_generated_tests_pass_and_branches_match_the_simulator(tmp_path):
    wf = routed_workflow()
    cases = []
    for i in range(10):
        sim = asyncio.run(run_case(wf, {"id": f"c{i}", "name": f"seed {i}", "input": {"message": "hi"}, "assertions": [], "seed": None}, i, 0))
        assertions = [{"type": "visits_node" if n.id in set(sim.path) else "skips_node", "node_id": n.id} for n in wf.nodes]
        cases.append({"name": f"seed {i}", "input": {"message": "hi"}, "assertions": assertions, "seed": None})
    result = run_generated_tests(write_project(export(wf, cases), tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 passed" in result.stdout


def test_cli_is_reproducible_and_prints_json_only_on_stdout(tmp_path):
    project = write_project(export(routed_workflow()), tmp_path)
    first = run_py(project, "main.py", "--mock", "--seed", "3", "--input", '{"message": "hello"}')
    assert first.returncode == 0, first.stderr
    out = json.loads(first.stdout)
    assert out["message"] == "hello" and out["tier"] in ("basic", "premium")
    assert run_py(project, "main.py", "--mock", "--seed", "3", "--input", '{"message": "hello"}').stdout == first.stdout
    assert json.loads(run_py(project, "main.py", "--mock").stdout)["message"] == "hello"        # falls back to the sample input


def test_human_review_asks_and_respects_the_answer(tmp_path):
    wf = Workflow(id="w", name="Review", nodes=[N("s", NodeType.START), N("h", NodeType.HITL, "Manager approval", config={"instructions": "Check the amount"}), N("e", NodeType.END)],
                  edges=[E("s", "h"), E("h", "e")])
    project = write_project(export(wf), tmp_path)
    auto = run_py(project, "main.py", "--mock", "--auto-approve", "--input", '{"amount": 5}')
    assert json.loads(auto.stdout) == {"amount": 5, "approved": True, "decision": "approve"}
    assert "Check the amount" in auto.stderr and "Manager approval" in auto.stderr

    env = {k: v for k, v in os.environ.items() if not k.startswith(("AIFLOW_", "PYTHON", "OPENAI"))}
    asked = subprocess.run([sys.executable, "main.py", "--mock", "--input", '{"amount": 5}'], cwd=project, input="reject\n",
                           capture_output=True, text=True, timeout=120, encoding="utf-8", env=env)
    assert json.loads(asked.stdout)["approved"] is False                    # the prompt went to stderr, stdout is still JSON
    assert "approve / reject >" in asked.stderr


def test_a_review_without_a_handler_says_what_to_do(tmp_path):
    wf = Workflow(id="w", name="Review", nodes=[N("s", NodeType.START), N("h", NodeType.HITL, "Approval"), N("e", NodeType.END)], edges=[E("s", "h"), E("h", "e")])
    project = write_project(export(wf), tmp_path)
    code = "import engine; engine.run({})"
    result = subprocess.run([sys.executable, "-c", code], cwd=project, capture_output=True, text=True, timeout=60, encoding="utf-8",
                            env={**{k: v for k, v in os.environ.items() if not k.startswith(("AIFLOW_", "PYTHON"))}, "AIFLOW_MOCK": "1"})
    assert result.returncode != 0 and "no review handler is set" in result.stderr


def test_decision_with_no_matching_branch_fails_loudly(tmp_path):
    wf = Workflow(id="w", name="Bad labels",
                  nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Decide", config={"expression": "input.amount > 5"}), N("a", NodeType.END, "A"), N("b", NodeType.END, "B")],
                  edges=[E("s", "c"), E("c", "a", "positive"), E("c", "b", "negative")])
    result = run_py(write_project(export(wf), tmp_path), "main.py", "--mock", "--input", '{"amount": 9}')
    assert result.returncode != 0 and "matches none of its branches (negative, positive)" in result.stderr


def test_each_step_runs_once_even_when_branches_rejoin_or_loop(tmp_path):
    diamond = Workflow(id="w", name="Diamond",
                       nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("j", NodeType.TRANSFORM, "Join"), N("e", NodeType.END)],
                       edges=[E("s", "a"), E("s", "b"), E("a", "j"), E("b", "j"), E("j", "e")])
    project = write_project(export(diamond), tmp_path / "diamond")
    out = subprocess.run([sys.executable, "-c", "import engine, json; print(json.dumps(engine.run({})['visited']))"], cwd=project, capture_output=True,
                         text=True, timeout=60, encoding="utf-8", env={**os.environ, "AIFLOW_MOCK": "1", "PYTHONPATH": ""})
    visited = json.loads(out.stdout)
    assert sorted(visited) == ["a", "b", "e", "j", "s"] and visited.count("j") == 1

    loop = Workflow(id="w", name="Loop",
                    nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("e", NodeType.END)],
                    edges=[E("s", "a"), E("a", "b"), E("b", "a"), E("b", "e")])
    result = run_py(write_project(export(loop), tmp_path / "loop"), "main.py", "--mock", "--input", "{}")
    assert result.returncode == 0, result.stderr                       # terminates instead of spinning


def test_hostile_text_is_data_not_code(tmp_path):
    evil = '"""\nimport os; open("PWNED", "w").write("x")\n#'
    wf = Workflow(id="w", name=evil, description=evil,
                  nodes=[N("s", NodeType.START, evil), N("l", NodeType.LLM, evil, config={"prompt": evil}), N("c", NodeType.CONDITION, evil, config={"expression": "true"}),
                         N("t", NodeType.TOOL, evil, config={"name": evil}), N("e", NodeType.END, evil)],
                  edges=[E("s", "l"), E("l", "c"), E("c", "t", "true"), E("c", "e", evil), E("t", "e")])
    files = export(wf)
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text)
    project = write_project(files, tmp_path)
    assert run_generated_tests(project).returncode == 0
    run_py(project, "main.py", "--mock", "--input", "{}")
    assert not (project / "PWNED").exists()


def test_real_connectors_work_in_the_plain_target_too(tmp_path, server):
    base, seen = server
    wf = chain(N("api", NodeType.API, "Customer", config={"method": "GET", "url": base + "/customers/{{customerId}}"}))
    result = run_py(write_project(export(wf), tmp_path), "main.py", "--input", '{"customerId": "a b"}')
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["status"] == 200 and out["body"]["id"] == "a%20b" and seen[0]["path"] == "/customers/a%20b"

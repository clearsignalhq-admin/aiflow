"""The exported API / DATABASE / RAG steps do real work (Task 54).

Each test generates a project and runs its command-line runner in a separate process (no mock mode):
API steps talk to a local HTTP server, DATABASE steps to a SQLite file, RAG steps to a knowledge folder.
"""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.services.langgraph_exporter import LangGraphExporter
from tests.test_langgraph_exporter import E, N, run_py, write_project


def workflow(*steps, name="Connectors") -> Workflow:
    """START → steps... → END"""
    nodes = [N("s", NodeType.START), *steps, N("e", NodeType.END)]
    ids = [n.id for n in nodes]
    return Workflow(id="w", name=name, nodes=nodes, edges=[E(a, b) for a, b in zip(ids, ids[1:])])


def run(project, data: dict, env=None):
    return run_py(project, "main.py", "--input", json.dumps(data), env=env)


# ═══════════════════════════ API ═══════════════════════════

class _Handler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def _respond(self, status: int, payload, raw: bytes | None = None):
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if raw is None else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        _Handler.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
        return body

    def do_GET(self):
        self._record()
        if self.path.startswith("/customers/"):
            self._respond(200, {"id": self.path.rsplit("/", 1)[1], "plan": "gold"})
        elif self.path == "/text":
            self._respond(200, None, raw=b"plain words")
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        body = self._record()
        if self.path == "/boom":
            self._respond(500, {"error": "server exploded"})
        else:
            self._respond(201, {"created": True, "echo": body})


@pytest.fixture
def server():
    _Handler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.requests
    httpd.shutdown()
    thread.join(timeout=5)


def test_api_get_percent_encodes_placeholders_and_returns_status_and_body(tmp_path, server):
    base, seen = server
    wf = workflow(N("api", NodeType.API, "Customer", config={"method": "GET", "url": base + "/customers/{{customerId}}"}))
    result = run(write_project(LangGraphExporter().export(wf), tmp_path), {"customerId": "a/b c"})
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["status"] == 200 and out["body"] == {"id": "a%2Fb%20c", "plan": "gold"}
    assert seen[0]["path"] == "/customers/a%2Fb%20c"                         # the slash could not escape the path segment
    assert out["customerId"] == "a/b c"                                       # earlier data is kept


def test_api_post_sends_json_headers_from_env_and_the_requested_fields_only(tmp_path, server):
    base, seen = server
    wf = workflow(N("api", NodeType.API, "Create", config={
        "method": "POST", "url": base + "/orders",
        "headers": {"Authorization": "env:SERVICE_TOKEN", "X-Customer": "{{customerId}}"},
        "requestSchema": {"type": "object", "properties": {"customerId": {}, "amount": {}}},
    }))
    data = {"customerId": "c1", "amount": 12, "secretNote": "do not send"}
    out = json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path), data, env={"SERVICE_TOKEN": "Bearer t0k3n"}).stdout)
    assert out["status"] == 201 and out["body"]["created"] is True
    sent = seen[0]
    assert sent["method"] == "POST" and sent["body"] == {"customerId": "c1", "amount": 12}     # secretNote stays home
    assert sent["headers"]["Authorization"] == "Bearer t0k3n" and sent["headers"]["X-Customer"] == "c1"


def test_api_body_template_keeps_types(tmp_path, server):
    base, seen = server
    wf = workflow(N("api", NodeType.API, "Create", config={
        "method": "POST", "url": base + "/orders", "body": {"qty": "{{quantity}}", "note": "for {{who}}", "tags": ["{{tag}}"]},
    }))
    run(write_project(LangGraphExporter().export(wf), tmp_path), {"quantity": 3, "who": "Ann", "tag": "vip"})
    assert seen[0]["body"] == {"qty": 3, "note": "for Ann", "tags": ["vip"]}


def test_api_error_status_is_data_a_decision_can_route_on(tmp_path, server):
    base, _ = server
    wf = Workflow(
        id="w", name="Retry or stop",
        nodes=[N("s", NodeType.START), N("api", NodeType.API, "Call", config={"method": "POST", "url": base + "/boom"}),
               N("c", NodeType.CONDITION, "Failed?", config={"expression": "input.status >= 400"}),
               N("fallback", NodeType.TRANSFORM, "Fallback"), N("ok", NodeType.END, "Ok"), N("end", NodeType.END, "Done")],
        edges=[E("s", "api"), E("api", "c"), E("c", "end", "true"), E("c", "ok", "false")],
    )
    result = run(write_project(LangGraphExporter().export(wf), tmp_path), {})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == 500


def test_api_text_response_and_missing_fields_and_bad_urls(tmp_path, server):
    base, _ = server
    wf = workflow(N("api", NodeType.API, "Text", config={"method": "GET", "url": base + "/text"}))
    assert json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path / "a"), {}).stdout)["body"] == "plain words"

    missing = workflow(N("api", NodeType.API, "Needs id", config={"method": "GET", "url": base + "/customers/{{customerId}}"}))
    result = run(write_project(LangGraphExporter().export(missing), tmp_path / "b"), {})
    assert result.returncode != 0 and "The field 'customerId' is not available" in result.stderr

    bad = workflow(N("api", NodeType.API, "Bad", config={"method": "GET", "url": "file:///etc/passwd"}))
    result = run(write_project(LangGraphExporter().export(bad), tmp_path / "c"), {})
    assert result.returncode != 0 and "must start with http" in result.stderr

    method = workflow(N("api", NodeType.API, "Odd", config={"method": "TRACE", "url": base}))
    assert "Unsupported HTTP method" in run(write_project(LangGraphExporter().export(method), tmp_path / "d"), {}).stderr


def test_api_missing_secret_env_names_the_variable(tmp_path, server):
    base, _ = server
    wf = workflow(N("api", NodeType.API, "Auth", config={"method": "GET", "url": base + "/text", "headers": {"Authorization": "env:SERVICE_TOKEN"}}))
    result = run(write_project(LangGraphExporter().export(wf), tmp_path), {})
    assert result.returncode != 0 and "Set the environment variable SERVICE_TOKEN" in result.stderr


# ═══════════════════════════ DATABASE ═══════════════════════════

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    con = sqlite3.connect(path)
    con.executescript("create table users (id integer primary key, name text, balance real);"
                      "insert into users values (1, 'Ann', 10.5), (2, 'Bob', 20);")
    con.commit()
    con.close()
    return path, {"DB_URL": f"sqlite:///{path.as_posix()}"}


def db_step(query: str, **extra) -> WorkflowNode:
    return N("db", NodeType.DATABASE, "Query", config={"type": "sqlite", "connection": "env:DB_URL", "query": query, **extra})



def test_select_returns_rows_bound_to_parameters(tmp_path, db):
    _, env = db
    wf = workflow(db_step("SELECT id, name, balance FROM users WHERE id = {{userId}}"))
    out = json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path / "p"), {"userId": 2}, env=env).stdout)
    assert out["rows"] == [{"id": 2, "name": "Bob", "balance": 20.0}] and out["row_count"] == 1


def test_values_are_never_spliced_into_the_sql(tmp_path, db):
    path, env = db
    wf = workflow(db_step("SELECT name FROM users WHERE name = {{who}}"))
    project = write_project(LangGraphExporter().export(wf), tmp_path / "p")
    attack = run(project, {"who": "Ann' OR '1'='1"}, env=env)
    assert json.loads(attack.stdout)["rows"] == []                      # treated as a name, not as SQL
    drop = run(project, {"who": "x'; DROP TABLE users; --"}, env=env)
    assert json.loads(drop.stdout)["rows"] == []
    assert sqlite3.connect(path).execute("select count(*) from users").fetchone()[0] == 2


def test_write_commits_and_reports_row_count(tmp_path, db):
    path, env = db
    wf = workflow(db_step("UPDATE users SET balance = balance + {{amount}} WHERE id = {{userId}}"))
    out = json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path / "p"), {"amount": 5, "userId": 1}, env=env).stdout)
    assert out["rows"] == [] and out["row_count"] == 1
    assert sqlite3.connect(path).execute("select balance from users where id = 1").fetchone()[0] == 15.5


def test_the_same_placeholder_twice_and_nested_fields(tmp_path, db):
    _, env = db
    wf = workflow(db_step("SELECT id FROM users WHERE id = {{pick.id}} OR id = {{pick.id}} + 1 ORDER BY id"))
    out = json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path / "p"), {"pick": {"id": 1}}, env=env).stdout)
    assert [r["id"] for r in out["rows"]] == [1, 2]


def test_row_limit(tmp_path, db):
    _, env = db
    wf = workflow(db_step("SELECT id FROM users ORDER BY id"))
    out = json.loads(run(write_project(LangGraphExporter().export(wf), tmp_path / "p"), {}, env={**env, "AIFLOW_MAX_ROWS": "1"}).stdout)
    assert out["row_count"] == 1


def test_connection_must_come_from_the_environment(tmp_path, db):
    _, env = db
    inline = N("db", NodeType.DATABASE, "Q", config={"connection": "postgresql://user:secret@host/db", "query": "SELECT 1"})
    result = run(write_project(LangGraphExporter().export(workflow(inline)), tmp_path / "a"), {}, env=env)
    assert result.returncode != 0 and "env:NAME" in result.stderr and "secret" not in result.stdout

    result = run(write_project(LangGraphExporter().export(workflow(db_step("SELECT 1"))), tmp_path / "b"), {})
    assert result.returncode != 0 and "Set the environment variable DB_URL" in result.stderr

    result = run(write_project(LangGraphExporter().export(workflow(db_step("SELECT {{missing}}"))), tmp_path / "c"), {}, env=env)
    assert result.returncode != 0 and "'missing' is not available" in result.stderr


# ═══════════════════════════ RAG ═══════════════════════════

@pytest.fixture
def knowledge(tmp_path):
    def build(project):
        kb = project / "knowledge" / "support-docs"
        kb.mkdir(parents=True)
        (kb / "refunds.md").write_text("# Refunds\n\nCustomers can request a refund within 30 days of purchase. Refunds go back to the original payment method.\n", encoding="utf-8")
        (kb / "shipping.txt").write_text("Shipping takes three to five business days.\n\nExpress shipping is available for an extra fee.", encoding="utf-8")
        (kb / "ignored.pdf").write_text("refund refund refund", encoding="utf-8")
        return kb
    return build


def rag_step(**config) -> WorkflowNode:
    return N("rag", NodeType.RAG, "Docs", config={"knowledgeBase": "support-docs", **config})


def test_keyword_search_ranks_the_relevant_document_first_without_an_api_key(tmp_path, knowledge):
    project = write_project(LangGraphExporter().export(workflow(rag_step(topK=2))), tmp_path)
    knowledge(project)
    out = json.loads(run(project, {"question": "How do I get a refund?"}).stdout)
    docs = out["documents"]
    assert docs[0]["source"] == "refunds.md" and "30 days" in docs[0]["content"] and docs[0]["score"] > 0
    assert len(docs) <= 2 and all(d["source"] != "ignored.pdf" for d in docs)
    assert "30 days" in out["context"]


def test_threshold_top_k_and_custom_query(tmp_path, knowledge):
    project = write_project(LangGraphExporter().export(workflow(rag_step(topK=1, query="express shipping {{speed}}"))), tmp_path)
    knowledge(project)
    out = json.loads(run(project, {"speed": "fee"}).stdout)
    assert len(out["documents"]) == 1 and out["documents"][0]["source"] == "shipping.txt"

    strict = write_project(LangGraphExporter().export(workflow(rag_step(similarityThreshold=0.99))), tmp_path / "strict")
    knowledge(strict)
    assert json.loads(run(strict, {"question": "refund"}).stdout)["documents"] == []

    plain = write_project(LangGraphExporter().export(workflow(rag_step())), tmp_path / "plain")
    knowledge(plain)
    nothing = json.loads(run(plain, {"question": "zzzqqq"}).stdout)           # no word in common with any document
    assert nothing["documents"] == [] and nothing["context"] == ""


def test_missing_or_empty_knowledge_folder_explains_what_to_create(tmp_path):
    project = write_project(LangGraphExporter().export(workflow(rag_step())), tmp_path)
    result = run(project, {"question": "x"})
    assert result.returncode != 0 and "Create the folder" in result.stderr and "support-docs" in result.stderr
    (project / "knowledge" / "support-docs").mkdir(parents=True)
    assert "has no .md or .txt files" in run(project, {"question": "x"}).stderr


def test_knowledge_base_names_cannot_escape_the_knowledge_folder(tmp_path, knowledge):
    project = write_project(LangGraphExporter().export(workflow(rag_step(knowledgeBase="../../secrets"))), tmp_path)
    (project / "secrets").mkdir()
    (project / "secrets" / "key.txt").write_text("the password is hunter2", encoding="utf-8")
    result = run(project, {"question": "password"})
    assert "hunter2" not in result.stdout and result.returncode != 0       # sanitised to knowledge/secrets, which does not exist

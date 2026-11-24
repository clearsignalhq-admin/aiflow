"""Cloud workflows, versions, diff, restore and share links (Task 61). Supabase is replaced by an in-memory fake."""
import copy
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import cloud_routes
from app.main import app
from app.models.workflow import NodeType, Workflow
from tests.conftest import DEMO_USER
from tests.test_run_comparison import E, N  # noqa: F401
from tests.test_suites import APPROVED_USER, as_user  # noqa: F401

BASE = "http://test"


class FakeCloud:
    def __init__(self):
        self.rows, self.versions = {}, []
        self.fail_version_insert = None

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    async def list_cloud_workflows(self, user_id):
        return [copy.deepcopy(r) for r in self.rows.values() if r["user_id"] == user_id]

    async def count_cloud_workflows(self, user_id):
        return len(await self.list_cloud_workflows(user_id))

    async def get_cloud_workflow(self, user_id, wid):
        r = self.rows.get(wid)
        return copy.deepcopy(r) if r and r["user_id"] == user_id else None

    async def get_cloud_workflow_by_token(self, token):
        for r in self.rows.values():
            if r.get("share_token") == token:
                return {k: copy.deepcopy(r.get(k)) for k in ("name", "workflow", "shared_at")}
        return None

    async def insert_cloud_workflow(self, record):
        row = {**copy.deepcopy(record), "id": str(uuid.uuid4()), "created_at": self._now(), "updated_at": self._now(), "share_token": None, "shared_at": None}
        self.rows[row["id"]] = row
        return copy.deepcopy(row)

    async def update_cloud_workflow(self, user_id, wid, patch_):
        r = self.rows.get(wid)
        if not r or r["user_id"] != user_id:
            return None
        r.update(copy.deepcopy(patch_))
        r["updated_at"] = self._now()
        return copy.deepcopy(r)

    async def delete_cloud_workflow(self, user_id, wid):
        r = self.rows.get(wid)
        if not r or r["user_id"] != user_id:
            return False
        del self.rows[wid]
        self.versions = [v for v in self.versions if v["workflow_id"] != wid]
        return True

    async def insert_workflow_version(self, record):
        if self.fail_version_insert is not None:
            raise self.fail_version_insert
        if any(v["workflow_id"] == record["workflow_id"] and v["version"] == record["version"] for v in self.versions):
            raise httpx.HTTPStatusError("duplicate", request=httpx.Request("POST", "http://x"), response=httpx.Response(409))
        row = {**copy.deepcopy(record), "created_at": self._now()}
        self.versions.append(row)
        return copy.deepcopy(row)

    async def list_workflow_versions(self, user_id, wid):
        return sorted((copy.deepcopy(v) for v in self.versions if v["workflow_id"] == wid and v["user_id"] == user_id), key=lambda v: -v["version"])

    async def get_workflow_version(self, user_id, wid, number):
        return next((copy.deepcopy(v) for v in self.versions if v["workflow_id"] == wid and v["user_id"] == user_id and v["version"] == number), None)

    async def prune_workflow_versions(self, user_id, wid, keep):
        mine = sorted((v for v in self.versions if v["workflow_id"] == wid), key=lambda v: -v["version"])
        for v in mine[keep:]:
            self.versions.remove(v)


@pytest.fixture
def fake():
    db = FakeCloud()
    with patch.object(cloud_routes, "db", db):
        yield db


@pytest.fixture
def client(fake, as_user):
    as_user(APPROVED_USER)
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


def wf(name="Flow", extra=None):
    nodes = [N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A", config={"v": 1}), N("e", NodeType.END)]
    edges = [E("s", "a"), E("a", "e")]
    for x in extra or []:
        nodes.insert(2, N(x, NodeType.TRANSFORM, x.title()))
        edges = [E("s", "a"), E("a", x), E(x, "e")]
    return Workflow(id="wf-1", name=name, nodes=nodes, edges=edges).model_dump(mode="json")


async def create(c, name="My flow", workflow=None, label=None):
    res = await c.post("/api/cloud/workflows", json={"name": name, "workflow": workflow or wf(), "label": label})
    assert res.status_code == 201, res.text
    return res.json()


# ── Create, list, open, delete ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_list_open_delete(client, fake):
    async with client as c:
        made = await create(c, "Support triage", label="first")
        assert made["version_count"] == 1 and made["shared"] is False and made["share_token"] is None
        listing = (await c.get("/api/cloud/workflows")).json()
        assert [(w["name"], w["version_count"], w["shared"]) for w in listing] == [("Support triage", 1, False)]
        assert "share_token" not in listing[0] and "workflow" not in listing[0]
        opened = (await c.get(f"/api/cloud/workflows/{made['id']}")).json()
        assert opened["workflow"]["name"] == "Flow" and len(opened["workflow"]["nodes"]) == 3
        assert (await c.delete(f"/api/cloud/workflows/{made['id']}")).status_code == 204
        assert (await c.get(f"/api/cloud/workflows/{made['id']}")).status_code == 404
        assert (await c.delete(f"/api/cloud/workflows/{made['id']}")).status_code == 404
    assert fake.versions == []                                                        # versions go with it


@pytest.mark.asyncio
async def test_name_defaults_to_the_workflow_name_and_input_is_validated(client):
    async with client as c:
        made = (await c.post("/api/cloud/workflows", json={"workflow": wf("From workflow")})).json()
        assert made["name"] == "From workflow"
        assert (await c.post("/api/cloud/workflows", json={"name": "x", "workflow": {"nodes": "bad"}})).status_code == 422
        assert (await c.post("/api/cloud/workflows", json={"name": "", "workflow": wf()})).status_code == 422
        assert (await c.get("/api/cloud/workflows/not-a-uuid")).status_code == 404


@pytest.mark.asyncio
async def test_the_per_user_limit(client):
    with patch.object(cloud_routes.settings, "max_cloud_workflows_per_user", 2):
        async with client as c:
            await create(c, "one")
            await create(c, "two")
            res = await c.post("/api/cloud/workflows", json={"name": "three", "workflow": wf()})
    assert res.status_code == 409 and "at most 2" in res.json()["detail"]


@pytest.mark.asyncio
async def test_people_only_see_their_own(client, as_user):
    async with client as c:
        made = await create(c)
        as_user(DEMO_USER)
        assert (await c.get("/api/cloud/workflows")).json() == []
        for method, path in [("get", ""), ("put", ""), ("delete", ""), ("get", "/versions"), ("get", "/versions/1"), ("post", "/share"), ("get", "/diff?base=1")]:
            res = await getattr(c, method)(f"/api/cloud/workflows/{made['id']}{path}", **({"json": {"workflow": wf()}} if method == "put" else {}))
            assert res.status_code == 404, (method, path)


# ── Saving and versions ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_saving_changes_adds_a_version_and_saving_the_same_adds_none(client):
    async with client as c:
        made = await create(c)
        same = (await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf()})).json()
        assert same["new_version"] is False and same["version_count"] == 1
        changed = (await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["b"]), "label": "added b"})).json()
        assert changed["new_version"] is True and changed["version_count"] == 2 and len(changed["workflow"]["nodes"]) == 4
        versions = (await c.get(f"/api/cloud/workflows/{made['id']}/versions")).json()
        assert [(v["version"], v["label"], v["node_count"]) for v in versions] == [(2, "added b", 4), (1, None, 3)]


@pytest.mark.asyncio
async def test_a_rename_alone_does_not_add_a_version(client):
    async with client as c:
        made = await create(c, "Old")
        res = (await c.put(f"/api/cloud/workflows/{made['id']}", json={"name": "New", "workflow": wf()})).json()
        assert res["name"] == "New" and res["new_version"] is False and res["version_count"] == 1
        both = (await c.put(f"/api/cloud/workflows/{made['id']}", json={"name": "Newer", "workflow": wf(extra=["b"])})).json()
        assert both["name"] == "Newer" and both["version_count"] == 2


@pytest.mark.asyncio
async def test_old_versions_are_pruned(client, fake):
    with patch.object(cloud_routes.settings, "max_versions_per_workflow", 3):
        async with client as c:
            made = await create(c)
            for i in range(5):
                await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(f"v{i}")})
            versions = (await c.get(f"/api/cloud/workflows/{made['id']}/versions")).json()
            gone = await c.get(f"/api/cloud/workflows/{made['id']}/versions/1")
    assert [v["version"] for v in versions] == [6, 5, 4] and gone.status_code == 404 and "removed" in gone.json()["detail"]


@pytest.mark.asyncio
async def test_a_save_that_races_another_is_a_clear_conflict_and_other_failures_are_not_hidden(client, fake):
    async with client as c:
        made = await create(c)
        fake.versions.append({"workflow_id": made["id"], "user_id": APPROVED_USER.id, "version": 2, "label": None, "workflow": wf("x"), "created_at": "t"})
        clash = await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["b"])})
        assert clash.status_code == 409 and "same moment" in clash.json()["detail"]
        assert (await c.get(f"/api/cloud/workflows/{made['id']}")).json()["version_count"] == 1       # the failed save changed nothing
    fake.fail_version_insert = httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(500))
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url=BASE) as c2:
        assert (await c2.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["c"])})).status_code == 500


# ── Diff and restore ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diff_between_versions_and_against_current(client):
    async with client as c:
        made = await create(c)
        await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["b"])})
        vs_current = (await c.get(f"/api/cloud/workflows/{made['id']}/diff?base=1")).json()
        assert vs_current["head_version"] is None and vs_current["diff"]["changed"]
        assert [(n["node_id"], n["change"]) for n in vs_current["diff"]["nodes"]] == [("b", "added")]
        assert {(e["change"], e["source"], e["target"]) for e in vs_current["diff"]["edges"]} == {("added", "a", "b"), ("added", "b", "e"), ("removed", "a", "e")}
        explicit = (await c.get(f"/api/cloud/workflows/{made['id']}/diff?base=1&head=2")).json()
        assert explicit["diff"] == vs_current["diff"]
        same = (await c.get(f"/api/cloud/workflows/{made['id']}/diff?base=2")).json()
        assert same["diff"]["changed"] is False
        assert (await c.get(f"/api/cloud/workflows/{made['id']}/diff?base=9")).status_code == 404
        assert (await c.get(f"/api/cloud/workflows/{made['id']}/diff?base=0")).status_code == 422
        assert (await c.get(f"/api/cloud/workflows/{made['id']}/diff")).status_code == 422


@pytest.mark.asyncio
async def test_restore_adds_a_new_version_and_keeps_history(client):
    async with client as c:
        made = await create(c)
        await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["b"])})
        restored = (await c.post(f"/api/cloud/workflows/{made['id']}/versions/1/restore")).json()
        assert restored["new_version"] is True and restored["version_count"] == 3 and len(restored["workflow"]["nodes"]) == 3
        versions = (await c.get(f"/api/cloud/workflows/{made['id']}/versions")).json()
        assert [(v["version"], v["label"]) for v in versions] == [(3, "Restored from version 1"), (2, None), (1, None)]
        again = (await c.post(f"/api/cloud/workflows/{made['id']}/versions/1/restore")).json()
        assert again["new_version"] is False and again["version_count"] == 3          # already the current copy
        assert (await c.post(f"/api/cloud/workflows/{made['id']}/versions/9/restore")).status_code == 404
        v1 = (await c.get(f"/api/cloud/workflows/{made['id']}/versions/1")).json()
        assert v1["version"] == 1 and len(v1["workflow"]["nodes"]) == 3


# ── Sharing ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_share_link_gives_read_only_access_without_signing_in(client, as_user):
    async with client as c:
        made = await create(c, "Public demo")
        token = (await c.post(f"/api/cloud/workflows/{made['id']}/share")).json()["share_token"]
        assert len(token) >= 40
        assert (await c.post(f"/api/cloud/workflows/{made['id']}/share")).json()["share_token"] == token       # idempotent
        assert (await c.get("/api/cloud/workflows")).json()[0]["shared"] is True
        assert (await c.get(f"/api/cloud/workflows/{made['id']}")).json()["share_token"] == token

    app.dependency_overrides.clear()                                                  # a visitor: no sign-in at all
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as visitor:
        res = await visitor.get(f"/api/shared/{token}")
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "Public demo" and len(body["workflow"]["nodes"]) == 3 and set(body) == {"name", "workflow", "shared_at"}
        for method in ("put", "post", "delete", "patch"):
            assert (await getattr(visitor, method)(f"/api/shared/{token}")).status_code == 405
        assert (await visitor.get(f"/api/cloud/workflows/{made['id']}")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_the_link_shows_the_current_copy_and_stops_working_when_unshared(client):
    async with client as c:
        made = await create(c)
        token = (await c.post(f"/api/cloud/workflows/{made['id']}/share")).json()["share_token"]
        await c.put(f"/api/cloud/workflows/{made['id']}", json={"workflow": wf(extra=["b"])})
        assert len((await c.get(f"/api/shared/{token}")).json()["workflow"]["nodes"]) == 4
        assert (await c.delete(f"/api/cloud/workflows/{made['id']}/share")).json() == {"share_token": None}
        assert (await c.get(f"/api/shared/{token}")).status_code == 404
        new_token = (await c.post(f"/api/cloud/workflows/{made['id']}/share")).json()["share_token"]
        assert new_token != token and (await c.get(f"/api/shared/{token}")).status_code == 404


@pytest.mark.asyncio
async def test_bad_tokens_and_deleted_workflows_look_the_same(client):
    async with client as c:
        made = await create(c)
        token = (await c.post(f"/api/cloud/workflows/{made['id']}/share")).json()["share_token"]
        await c.delete(f"/api/cloud/workflows/{made['id']}")
        for t in (token, "short", "x" * 30, "a b c d e f g h i j k l m", "a" * 70):
            res = await c.get(f"/api/shared/{t}")
            assert res.status_code == 404 and res.json()["detail"] == "This link is not valid or is no longer shared."
        assert (await c.get("/api/shared/..%2F..%2Fetc%2Fpasswd")).status_code == 404


@pytest.mark.asyncio
async def test_endpoints_require_sign_in_except_the_share_link(fake):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        for method, path in [("get", "/api/cloud/workflows"), ("post", "/api/cloud/workflows"), ("get", f"/api/cloud/workflows/{uuid.uuid4()}")]:
            assert (await getattr(c, method)(path)).status_code in (401, 403, 422)

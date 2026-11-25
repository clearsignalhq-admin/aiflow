"""A local AiFlow backend for taking documentation screenshots. Not for production.

It is the real application (real validation, checks, simulation, safety drill, exports) with three differences:
  * everybody is signed in as a fixed demo user (no Supabase, no passwords);
  * saved things (test suites, cloud workflows) live in memory and vanish when it stops;
  * the AI provider is a canned stand-in, so no model is called and no key is needed.

Run from this folder so the real backend/.env (and its secrets) is never read:
    python server.py            # listens on 127.0.0.1:8000
"""
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "backend"))
os.environ.update({"SUPABASE_URL": "http://127.0.0.1:9", "SUPABASE_SERVICE_ROLE_KEY": "x", "SUPABASE_JWT_SECRET": "x",
                   "LLM_API_KEY": "docs", "CORS_ORIGINS": os.environ.get("CAPTURE_ORIGIN_JSON", '["http://localhost:5199"]'), "GIT_COMMIT": "docs"})

import uvicorn  # noqa: E402

from app.api import cloud_routes, routes, suites_routes  # noqa: E402
from app.api.deps import get_current_user, require_admin, require_approved  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import UserProfile  # noqa: E402
from app.services import run_persistence  # noqa: E402
from tests.test_cloud import FakeCloud  # noqa: E402
from tests.test_suites import FakeDB  # noqa: E402

USER = UserProfile(id="docs-user", email="ada@example.com", access_status="approved", role="user", must_change_password=False,
                   created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))


class CannedProvider:
    """Stands in for the AI model: 'generates' a worked example, so the Generate dialog can be shown end to end."""

    async def generate_workflow(self, description: str) -> dict:
        return json.loads((REPO / "examples" / "medium" / "customer-support.json").read_text(encoding="utf-8"))

    async def complete_json(self, system: str, user: str) -> dict:
        return {"summary": "No changes proposed in the documentation build.", "changes": []}


def main() -> None:
    for dep in (get_current_user, require_approved, require_admin):
        app.dependency_overrides[dep] = lambda: USER
    usage = {"executions": 3, "llm_requests": 2}
    patches = [
        patch.object(suites_routes, "db", FakeDB()),
        patch.object(cloud_routes, "db", FakeCloud()),
        patch.object(run_persistence, "_enabled", lambda: False),
        patch.object(routes, "get_usage_today", AsyncMock(return_value=usage)),
        patch("app.api.user_routes.get_usage_today", AsyncMock(return_value=usage)),
        patch.object(routes, "increment_usage", AsyncMock()),
        patch.object(routes, "insert_analytics_event", AsyncMock()),
        patch.object(routes, "get_provider", lambda: CannedProvider()),
        patch.object(suites_routes.settings, "approved_max_executions_per_day", 0),
    ]
    for p in patches:
        p.start()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()

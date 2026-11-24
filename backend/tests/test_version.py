"""The product version lives in one place (the root VERSION file) and everything else must agree with it."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.version import __version__

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "VERSION").exists(), reason="not running from the repository")


def version_file() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_is_a_semantic_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", version_file())


def test_every_copy_of_the_version_agrees():
    assert __version__ == version_file()
    assert json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"] == version_file()
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == version_file() and lock["packages"][""]["version"] == version_file()
    assert app.version == version_file()


def test_sync_script_reports_nothing_to_do():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_changelog_leads_with_the_current_version():
    first = next(line for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("## "))
    assert first.startswith(f"## {version_file()} ")


@pytest.mark.asyncio
async def test_health_reports_the_running_version_and_commit():
    from unittest.mock import patch
    from app.core.config import settings
    with patch.object(settings, "git_commit", "abc1234"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get("/api/health")
    assert res.json() == {"status": "ok", "version": version_file(), "commit": "abc1234"}

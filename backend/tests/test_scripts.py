"""The release and deploy helper scripts (their logic; nothing here runs sam or git)."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
pytestmark = pytest.mark.skipif(not SCRIPTS.exists(), reason="not running from the repository")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = load("bump_version") if SCRIPTS.exists() else None
deploy = load("deploy") if SCRIPTS.exists() else None


# ── bump_version ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("current,part,expected", [
    ("0.10.1", "patch", "0.10.2"),
    ("0.10.1", "minor", "0.11.0"),
    ("0.10.1", "major", "1.0.0"),
    ("1.9.9", "patch", "1.9.10"),
    ("0.0.0", "minor", "0.1.0"),
])
def test_bump(current, part, expected):
    assert bump_version.bump(current, part) == expected


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "", "1.2.x"])
def test_bump_rejects_a_malformed_version(bad):
    with pytest.raises(ValueError):
        bump_version.bump(bad, "patch")


def test_bump_rejects_an_unknown_part():
    with pytest.raises(ValueError):
        bump_version.bump("1.2.3", "huge")


def test_the_stub_goes_above_the_newest_entry_and_below_the_introduction():
    changelog = "# Changelog\n\nIntro text.\n\n## 0.10.1 — 2026-11-24\n\nOld.\n\n## 0.10.0 — 2026-11-23\n\nOlder.\n"
    stub = bump_version.changelog_stub("0.11.0", date(2026, 12, 1))
    out = bump_version.insert_stub(changelog, stub)
    assert out.startswith("# Changelog\n\nIntro text.\n\n## 0.11.0 — 2026-12-01\n")
    assert out.index("## 0.11.0") < out.index("## 0.10.1") < out.index("## 0.10.0")
    assert "Old." in out and "Older." in out                                       # nothing lost


def test_a_changelog_with_no_entries_is_refused():
    with pytest.raises(ValueError):
        bump_version.insert_stub("# Changelog\n\nOnly an introduction.\n", "## 1.0.0 — x\n")


def test_dry_run_changes_nothing(capsys):
    before = (SCRIPTS.parent / "VERSION").read_text(encoding="utf-8")
    assert bump_version.main(["patch", "--dry-run"]) == 0
    assert "->" in capsys.readouterr().out
    assert (SCRIPTS.parent / "VERSION").read_text(encoding="utf-8") == before


# ── deploy ───────────────────────────────────────────────────────────────────

SAMCONFIG = '''
version = 0.1
[default.global.parameters]
stack_name = "aiflow"
[default.deploy.parameters]
resolve_s3 = true
parameter_overrides = "SupabaseUrl=\\"https://x.supabase.co\\" FrontendOrigin=\\"main.example.com\\""
'''


def test_reads_the_configured_overrides():
    assert deploy.configured_overrides(SAMCONFIG) == 'SupabaseUrl="https://x.supabase.co" FrontendOrigin="main.example.com"'
    assert deploy.configured_overrides("version = 0.1\n") == ""
    assert deploy.configured_overrides(SAMCONFIG, section="other") == ""


def test_adds_the_commit_without_disturbing_the_rest():
    out = deploy.with_commit('SupabaseUrl="https://x.supabase.co" FrontendOrigin="main.example.com"', "abc1234")
    assert out == 'SupabaseUrl="https://x.supabase.co" FrontendOrigin="main.example.com" GitCommit=abc1234'
    assert deploy.with_commit("", "abc1234") == "GitCommit=abc1234"


def test_replaces_a_commit_already_there():
    assert deploy.with_commit('A="1" GitCommit=1111aaa B="2"', "2222abc") == 'A="1" B="2" GitCommit=2222abc'
    assert deploy.with_commit('GitCommit="1111aaa" A="1"', "2222abc") == 'A="1" GitCommit=2222abc'


@pytest.mark.parametrize("bad", ["", "xyz", "abc 123", "abc;rm", "ABCDEF", "a" * 41])
def test_refuses_anything_that_is_not_a_commit_id(bad):
    with pytest.raises(ValueError):
        deploy.with_commit("A=1", bad)


def test_the_plan_is_build_then_deploy():
    plan = deploy.commands(SAMCONFIG, "abc1234")
    assert plan[0] == ["sam", "build"]
    assert plan[1][:3] == ["sam", "deploy", "--parameter-overrides"]
    assert plan[1][3].endswith(" GitCommit=abc1234") and "SupabaseUrl" in plan[1][3]


def test_resolves_the_program_to_its_full_path():
    which = {"sam": r"C:\Program Files\Amazon\AWSSAMCLIin\sam.cmd"}.get
    assert deploy.resolve(["sam", "deploy", "--x"], which=which) == [r"C:\Program Files\Amazon\AWSSAMCLIin\sam.cmd", "deploy", "--x"]


def test_a_missing_program_gives_a_helpful_message():
    with pytest.raises(FileNotFoundError, match="'sam' was not found on the PATH"):
        deploy.resolve(["sam", "build"], which=lambda name: None)

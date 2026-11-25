"""deploy.py: offering to tag a release after a deploy (decisions, and the real git flow in a throwaway repository)."""
import argparse
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
pytestmark = pytest.mark.skipif(not SCRIPTS.exists(), reason="not running from the repository")


def load():
    spec = importlib.util.spec_from_file_location("deploy_under_test", SCRIPTS / "deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = load() if SCRIPTS.exists() else None


# ── Decisions (no git involved) ──────────────────────────────────────────────

def test_release_tag():
    assert deploy.release_tag("0.12.0") == "v0.12.0"
    assert deploy.release_tag(" 1.0.10\n") == "v1.0.10"
    for bad in ("", "v1.2.3", "1.2", "1.2.x", "1.2.3-beta"):
        with pytest.raises(ValueError):
            deploy.release_tag(bad)


LS_REMOTE = "aaa111\trefs/tags/v0.12.0\nbbb222\trefs/tags/v0.12.0^{}\nccc333\trefs/tags/v0.12.0-rc1\n"


def test_the_remote_commit_of_an_annotated_tag_is_the_commit_not_the_tag_object():
    assert deploy.parse_ls_remote(LS_REMOTE, "v0.12.0") == "bbb222"
    assert deploy.parse_ls_remote("ddd444\trefs/tags/v0.9.0\n", "v0.9.0") == "ddd444"           # a lightweight tag
    assert deploy.parse_ls_remote(LS_REMOTE, "v9.9.9") is None
    assert deploy.parse_ls_remote("", "v0.12.0") is None
    assert deploy.parse_ls_remote("garbage line\n\n", "v0.12.0") is None


@pytest.mark.parametrize("local,remote,expected", [
    (None, None, "missing"),
    ("abc", None, "here"),
    (None, "abc", "here"),
    ("abc", "abc", "here"),
    ("old", None, "elsewhere"),
    (None, "old", "elsewhere"),
    ("abc", "old", "elsewhere"),                         # the two disagree: never treat it as ours
])
def test_tag_state(local, remote, expected):
    assert deploy.tag_state("abc", local, remote) == expected


@pytest.mark.parametrize("state,flags,expected", [
    ("missing", dict(), "ask"),
    ("missing", dict(interactive=False), "hint"),                       # never prompt when there is no terminal
    ("missing", dict(tag_flag=True), "create"),
    ("missing", dict(tag_flag=True, interactive=False), "create"),
    ("missing", dict(no_tag=True), "skip"),
    ("missing", dict(dirty=True), "dirty"),                             # a dirty deploy is never tagged, even with --tag
    ("missing", dict(dirty=True, tag_flag=True), "dirty"),
    ("here", dict(), "already"),
    ("here", dict(tag_flag=True), "already"),
    ("elsewhere", dict(), "elsewhere"),
    ("elsewhere", dict(tag_flag=True), "elsewhere"),                    # an existing tag is never moved
    ("elsewhere", dict(no_tag=True), "skip"),
])
def test_decide_tag(state, flags, expected):
    options = dict(tag_flag=False, no_tag=False, dirty=False, interactive=True)
    assert deploy.decide_tag(state, **{**options, **flags}) == expected


@pytest.mark.parametrize("answer,expected", [("y", True), ("Y", True), (" yes ", True), ("YES", True), ("", False), ("n", False), ("no", False), ("yep", False)])
def test_only_a_clear_yes_confirms(answer, expected):
    assert deploy.confirmed(answer) is expected


CHANGELOG = """# Changelog

Intro.

## 0.12.0 — 2026-11-24

**New**
- Two new examples.

**Fixed**
- Something.

## 0.11.1 — 2026-11-24

**Fixed**
- Older.
"""


def test_tag_message_carries_the_release_notes_of_that_version_only():
    message = deploy.tag_message("0.12.0", CHANGELOG)
    assert message.startswith("AiFlow 0.12.0\n\n**New**\n- Two new examples.")
    assert "Something." in message and "Older." not in message and "## " not in message


def test_tag_message_is_short_and_copes_with_a_missing_entry():
    long = "## 1.0.0 — x\n\n" + "\n".join(f"- line {i}" for i in range(60)) + "\n"
    assert len(deploy.tag_message("1.0.0", long).splitlines()) <= deploy.MESSAGE_LINES + 2
    assert deploy.tag_message("9.9.9", CHANGELOG) == "AiFlow 9.9.9"
    assert deploy.tag_message("0.12.0", CHANGELOG.replace("\n", "\r\n")).startswith("AiFlow 0.12.0\n\n**New**")


# ── The real flow, against a throwaway repository and a local "remote" ───────

def _run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _run(tmp_path, "git", "init", "--bare", "-q", str(remote))
    _run(tmp_path, "git", "init", "-q", str(work))
    for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        _run(work, "git", "config", key, value)
    (work / "VERSION").write_text("0.12.0\n", encoding="utf-8")
    (work / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    _run(work, "git", "add", "-A")
    _run(work, "git", "commit", "-q", "-m", "release 0.12.0")
    _run(work, "git", "remote", "add", "origin", str(remote))
    monkeypatch.setattr(deploy, "ROOT", work)
    return work, remote


def _args(**kw):
    return argparse.Namespace(**{"tag": True, "no_tag": False, **kw})


def test_creates_an_annotated_tag_on_the_deployed_commit_and_pushes_it(repo, capsys):
    work, remote = repo
    head = _run(work, "git", "rev-parse", "HEAD")
    assert deploy.offer_tag(_args(), dirty=False) == 0
    assert _run(work, "git", "cat-file", "-t", "v0.12.0") == "tag"                              # annotated, not lightweight
    assert _run(work, "git", "rev-parse", "v0.12.0^{commit}") == head
    assert _run(remote, "git", "rev-parse", "v0.12.0^{commit}") == head                         # and it reached the remote
    assert "Two new examples." in _run(work, "git", "tag", "-l", "-n20", "v0.12.0")
    assert "Tagged" in capsys.readouterr().out


def test_a_second_run_finds_it_already_tagged_and_changes_nothing(repo, capsys):
    work, remote = repo
    deploy.offer_tag(_args(), dirty=False)
    capsys.readouterr()
    before = _run(remote, "git", "rev-parse", "refs/tags/v0.12.0")
    assert deploy.offer_tag(_args(), dirty=False) == 0
    assert "already points at this commit" in capsys.readouterr().out
    assert _run(remote, "git", "rev-parse", "refs/tags/v0.12.0") == before


def test_an_existing_tag_on_another_commit_is_never_moved(repo, capsys):
    work, remote = repo
    deploy.offer_tag(_args(), dirty=False)
    tagged = _run(work, "git", "rev-parse", "v0.12.0^{commit}")
    (work / "later.txt").write_text("a later commit, same version\n", encoding="utf-8")
    _run(work, "git", "add", "-A")
    _run(work, "git", "commit", "-q", "-m", "later")
    capsys.readouterr()
    assert deploy.offer_tag(_args(), dirty=False) == 0
    assert "was not moved" in capsys.readouterr().err
    assert _run(work, "git", "rev-parse", "v0.12.0^{commit}") == tagged
    assert _run(remote, "git", "rev-parse", "v0.12.0^{commit}") == tagged


def test_a_tag_that_exists_only_on_the_remote_is_respected(repo, capsys):
    work, remote = repo
    deploy.offer_tag(_args(), dirty=False)
    _run(work, "git", "tag", "-d", "v0.12.0")                                                    # gone locally, still on the remote
    capsys.readouterr()
    assert deploy.offer_tag(_args(), dirty=False) == 0
    assert "already points at this commit" in capsys.readouterr().out


def test_a_dirty_deploy_and_no_tag_do_nothing(repo, capsys):
    work, remote = repo
    assert deploy.offer_tag(_args(), dirty=True) == 0
    assert "uncommitted changes" in capsys.readouterr().out
    assert deploy.offer_tag(_args(no_tag=True), dirty=False) == 0
    assert _run(work, "git", "tag", "-l") == "" and _run(remote, "git", "tag", "-l") == ""


def test_asking_creates_the_tag_only_after_a_yes(repo, monkeypatch, capsys):
    work, remote = repo
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert deploy.offer_tag(_args(tag=False), dirty=False) == 0
    assert _run(work, "git", "tag", "-l") == ""
    assert "Not tagged" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert deploy.offer_tag(_args(tag=False), dirty=False) == 0
    assert _run(work, "git", "tag", "-l") == "v0.12.0" and _run(remote, "git", "tag", "-l") == "v0.12.0"


def test_without_a_terminal_it_only_prints_the_command(repo, monkeypatch, capsys):
    work, remote = repo
    monkeypatch.setattr("sys.stdin", type("Pipe", (), {"isatty": lambda self: False})())
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not prompt without a terminal"))
    assert deploy.offer_tag(_args(tag=False), dirty=False) == 0
    assert "git tag -a v0.12.0" in capsys.readouterr().out
    assert _run(work, "git", "tag", "-l") == ""


def test_a_failed_push_is_reported_as_a_failure_after_a_successful_deploy(repo, capsys):
    work, remote = repo
    _run(work, "git", "remote", "set-url", "origin", str(remote.parent / "does-not-exist.git"))
    assert deploy.offer_tag(_args(), dirty=False) == 1
    assert "deploy succeeded, but tagging failed" in capsys.readouterr().err

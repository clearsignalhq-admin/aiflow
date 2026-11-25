"""Build and deploy the backend with the current git commit stamped into it (shown in Help -> About), then offer to tag
the release.

    python scripts/deploy.py              # sam build, sam deploy, then offer to tag
    python scripts/deploy.py --dry-run    # print the commands (and what it would do about the tag), run nothing
    python scripts/deploy.py --tag        # tag the release without asking
    python scripts/deploy.py --no-tag     # deploy only

It reads the parameter overrides already in samconfig.toml and adds GitCommit=<short sha>, so everything else stays as
configured. Anything the config does not mention is left to SAM exactly as for a plain `sam deploy`. It refuses to run
with uncommitted changes, because the stamped commit would then not describe what is deployed (use --allow-dirty to
override; a deploy done that way is never tagged).

After a successful deploy it offers to create the annotated tag v<VERSION> on the deployed commit and push it. It never
moves a tag that already exists on another commit, never tags a dirty tree, and only asks when run from a terminal.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"\d+\.\d+\.\d+")
MESSAGE_LINES = 14                                 # how much of the changelog entry goes into the tag message


# ── Deploy ───────────────────────────────────────────────────────────────────

def configured_overrides(samconfig_text: str, section: str = "default") -> str:
    """The `parameter_overrides` string of the deploy section, or an empty string."""
    config = tomllib.loads(samconfig_text)
    return str(config.get(section, {}).get("deploy", {}).get("parameters", {}).get("parameter_overrides", "")).strip()


def with_commit(overrides: str, commit: str) -> str:
    """Add (or replace) GitCommit in a SAM overrides string such as `Key="value" Other=value`."""
    if not re.fullmatch(r"[0-9a-f]{4,40}", commit):
        raise ValueError(f"not a git commit id: {commit!r}")
    kept = re.sub(r'(?:^|\s)GitCommit=(?:"[^"]*"|\S*)', "", overrides).strip()
    return f"{kept} GitCommit={commit}".strip()


def commands(samconfig_text: str, commit: str) -> list[list[str]]:
    return [
        ["sam", "build"],
        ["sam", "deploy", "--parameter-overrides", with_commit(configured_overrides(samconfig_text), commit)],
    ]


def resolve(cmd: list[str], which=shutil.which) -> list[str]:
    """Replace the program name with its full path. On Windows the SAM CLI is `sam.cmd`, which a bare `sam` does not find
    when started from Python (a terminal does, because it searches the PATHEXT list)."""
    found = which(cmd[0])
    if not found:
        raise FileNotFoundError(
            f"'{cmd[0]}' was not found on the PATH. Install it (for the AWS SAM CLI: "
            "https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) "
            "and open a new terminal, or run the commands above by hand."
        )
    return [found, *cmd[1:]]


# ── Tagging: the decisions, kept free of git so they can be tested ────────────

def release_tag(version: str) -> str:
    version = version.strip()
    if not SEMVER.fullmatch(version):
        raise ValueError(f"not a version number: {version!r}")
    return f"v{version}"


def parse_ls_remote(output: str, tag: str) -> Optional[str]:
    """The commit a tag points at on the remote, from `git ls-remote` output. An annotated tag is listed twice: the tag
    object, and the commit it points at (marked ^{}); the commit is what matters."""
    plain = peeled = None
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref == f"refs/tags/{tag}^{{}}":
            peeled = sha
        elif ref == f"refs/tags/{tag}":
            plain = sha
    return peeled or plain


def tag_state(head: str, local: Optional[str], remote: Optional[str]) -> str:
    """'missing' (no such tag anywhere), 'here' (it already points at this commit) or 'elsewhere' (it points at another)."""
    existing = [c for c in (local, remote) if c]
    if not existing:
        return "missing"
    return "here" if all(c == head for c in existing) else "elsewhere"


def decide_tag(state: str, *, tag_flag: bool, no_tag: bool, dirty: bool, interactive: bool) -> str:
    """What to do about the tag: skip | dirty | already | elsewhere | create | ask | hint."""
    if no_tag:
        return "skip"
    if dirty:
        return "dirty"
    if state == "here":
        return "already"
    if state == "elsewhere":
        return "elsewhere"
    if tag_flag:
        return "create"
    return "ask" if interactive else "hint"


def confirmed(answer: str) -> bool:
    return answer.strip().lower() in ("y", "yes")


def tag_message(version: str, changelog: str) -> str:
    """`AiFlow 0.12.0` plus the start of that release's changelog entry (without its heading)."""
    lines = changelog.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith(f"## {version} ")), None)
    body: list[str] = []
    if start is not None:
        for line in lines[start + 1:]:
            if line.startswith("## "):
                break
            body.append(line.rstrip())
    while body and not body[0]:
        body.pop(0)
    body = body[:MESSAGE_LINES]
    while body and not body[-1]:
        body.pop()
    return f"AiFlow {version}" + ("\n\n" + "\n".join(body) if body else "")


# ── git ──────────────────────────────────────────────────────────────────────

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def git_try(*args: str) -> Optional[str]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def current_tag_state(tag: str, head: str) -> tuple[str, Optional[str]]:
    """(state, the commit the tag is on, if it exists). Looks locally and on `origin` (read only)."""
    local = git_try("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    listing = git_try("ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    remote = parse_ls_remote(listing, tag) if listing else None
    return tag_state(head, local, remote), local or remote


def offer_tag(args: argparse.Namespace, dirty: bool) -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = release_tag(version)
    head = git("rev-parse", "HEAD")
    state, existing = current_tag_state(tag, head)
    action = decide_tag(state, tag_flag=args.tag, no_tag=args.no_tag, dirty=dirty, interactive=sys.stdin.isatty())
    short = head[:7]
    message = tag_message(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

    if action == "skip":
        return 0
    if action == "dirty":
        print(f"\nNot offering a tag: the working tree had uncommitted changes, so {short} is not exactly what was deployed.")
        return 0
    if action == "already":
        print(f"\n{tag} already points at this commit ({short}). Nothing to tag.")
        return 0
    if action == "elsewhere":
        print(f"\n{tag} already exists on {str(existing)[:7]}, not on this commit ({short}); it was not moved.\n"
              f"If this is a new release, start it with: python scripts/bump_version.py patch|minor|major", file=sys.stderr)
        return 0
    if action == "hint":
        print(f"\nTo tag this release:\n  git tag -a {tag} -m \"AiFlow {version}\" && git push origin {tag}")
        return 0
    if action == "ask":
        print()
        if not confirmed(input(f"Tag commit {short} as {tag} and push the tag? [y/N] ")):
            print(f"Not tagged. To tag later: git tag -a {tag} -m \"AiFlow {version}\" && git push origin {tag}")
            return 0
    try:
        subprocess.run(["git", "tag", "-a", tag, head, "-m", message], cwd=ROOT, check=True)
        subprocess.run(["git", "push", "origin", tag], cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"\nThe deploy succeeded, but tagging failed ({exc}). Tag by hand: git tag -a {tag} {short} && git push origin {tag}", file=sys.stderr)
        return 1
    print(f"\nTagged {short} as {tag} and pushed it.")
    return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print what would run, change nothing")
    parser.add_argument("--allow-dirty", action="store_true", help="deploy with uncommitted changes (never tagged)")
    tagging = parser.add_mutually_exclusive_group()
    tagging.add_argument("--tag", action="store_true", help="tag the release after deploying, without asking")
    tagging.add_argument("--no-tag", action="store_true", help="do not offer to tag")
    args = parser.parse_args(argv)

    dirty = bool(git("status", "--porcelain"))
    if dirty and not args.allow_dirty:
        print("There are uncommitted changes, so the commit stamp would not describe what is deployed.\n"
              "Commit them first, or pass --allow-dirty.", file=sys.stderr)
        return 1
    plan = commands((ROOT / "samconfig.toml").read_text(encoding="utf-8"), git("rev-parse", "--short", "HEAD"))
    for cmd in plan:
        print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if args.dry_run:
        if dirty and not args.no_tag:
            print("\nBecause of the uncommitted changes, it would not offer a tag.")
        elif not args.no_tag:
            version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
            tag, head = release_tag(version), git("rev-parse", "HEAD")
            state, existing = current_tag_state(tag, head)
            print({"missing": f"\nAfter a successful deploy it would offer to tag {head[:7]} as {tag}.",
                   "here": f"\n{tag} already points at this commit; there would be nothing to tag.",
                   "elsewhere": f"\n{tag} already exists on {str(existing)[:7]}, not on this commit; it would not be moved."}[state])
        return 0
    try:
        resolved = [resolve(cmd) for cmd in plan]            # check everything is installed before running anything
    except FileNotFoundError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    for cmd in resolved:
        subprocess.run(cmd, cwd=ROOT, check=True)
    return offer_tag(args, dirty)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

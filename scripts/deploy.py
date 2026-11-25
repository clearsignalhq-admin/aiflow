"""Build and deploy the backend with the current git commit stamped into it (shown in Help -> About).

    python scripts/deploy.py              # sam build, then sam deploy
    python scripts/deploy.py --dry-run    # print the commands, run nothing

It reads the parameter overrides already in samconfig.toml and adds GitCommit=<short sha>, so everything else stays as
configured. Anything the config does not mention is left to SAM exactly as for a plain `sam deploy`. It refuses to run
with uncommitted changes, because the stamped commit would then not describe what is deployed (use --allow-dirty to
override).
"""
import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    if git("status", "--porcelain") and not args.allow_dirty:
        print("There are uncommitted changes, so the commit stamp would not describe what is deployed.\n"
              "Commit them first, or pass --allow-dirty.", file=sys.stderr)
        return 1
    plan = commands((ROOT / "samconfig.toml").read_text(encoding="utf-8"), git("rev-parse", "--short", "HEAD"))
    for cmd in plan:
        print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd))
        if not args.dry_run:
            subprocess.run(cmd, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

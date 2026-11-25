"""Start a new release: bump VERSION, add a CHANGELOG entry to fill in, and sync every copy of the number.

    python scripts/bump_version.py patch      # 0.10.1 -> 0.10.2  (a fix)
    python scripts/bump_version.py minor      # 0.10.1 -> 0.11.0  (a feature)
    python scripts/bump_version.py major      # 0.10.1 -> 1.0.0   (a breaking change, or leaving beta)
    python scripts/bump_version.py minor --dry-run

Afterwards: write the changelog entry (replace the placeholder), run the tests, commit, tag (`git tag vX.Y.Z`), deploy.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ("major", "minor", "patch")


def bump(version: str, part: str) -> str:
    if part not in PARTS:
        raise ValueError(f"part must be one of {', '.join(PARTS)}")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"not a version number: {version!r}")
    major, minor, patch = (int(x) for x in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def changelog_stub(version: str, today: date) -> str:
    return f"## {version} — {today.isoformat()}\n\n**Changed**\n- (describe what changed in this release)\n\n"


def insert_stub(changelog: str, stub: str) -> str:
    """Put the stub above the newest existing entry (and below the introduction)."""
    first = re.search(r"^## ", changelog, re.M)
    if not first:
        raise ValueError("CHANGELOG.md has no release entries to put the new one above")
    return changelog[: first.start()] + stub + changelog[first.start():]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("part", choices=PARTS)
    parser.add_argument("--dry-run", action="store_true", help="show the new version without changing anything")
    args = parser.parse_args(argv)

    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    new = bump(current, args.part)
    print(f"{current} -> {new}")
    if args.dry_run:
        return 0

    changelog_path = ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if re.search(rf"^## {re.escape(new)} ", changelog, re.M):
        print(f"CHANGELOG.md already has an entry for {new}; nothing changed.", file=sys.stderr)
        return 1
    changelog_path.write_text(insert_stub(changelog, changelog_stub(new, date.today())), encoding="utf-8", newline="\n")
    (ROOT / "VERSION").write_text(new + "\n", encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_version.py")], check=True)
    print(f"\nNext: fill in the {new} entry in CHANGELOG.md, run the tests, commit, then `git tag v{new}` and deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

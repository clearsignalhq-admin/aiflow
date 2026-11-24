"""Copy the product version from the root VERSION file to everywhere that needs it.

    python scripts/sync_version.py          # write
    python scripts/sync_version.py --check  # exit 1 if anything is out of step (used by the tests)

Edit VERSION (and add a CHANGELOG.md entry), run this, commit. Nothing else holds a hand-edited version number.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER.match(version):
        raise SystemExit(f"VERSION must look like 1.2.3, got {version!r}")
    return version


def targets(version: str) -> list[tuple[Path, str, str]]:
    """(file, current text, wanted text) for every file that carries the version."""
    out = []

    py = ROOT / "backend" / "app" / "version.py"
    wanted = f'"""The product version. Generated from the root VERSION file by scripts/sync_version.py; do not edit."""\n__version__ = "{version}"\n'
    out.append((py, py.read_text(encoding="utf-8") if py.exists() else "", wanted))

    pkg = ROOT / "frontend" / "package.json"
    text = pkg.read_text(encoding="utf-8")
    out.append((pkg, text, re.sub(r'("version"\s*:\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1)))

    lock = ROOT / "frontend" / "package-lock.json"
    if lock.exists():
        text = lock.read_text(encoding="utf-8")
        data = json.loads(text)
        if data.get("version") != version or data.get("packages", {}).get("", {}).get("version") != version:
            new = re.sub(r'("version"\s*:\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1)           # top-level entry
            new = re.sub(r'("packages"\s*:\s*\{\s*""\s*:\s*\{[^}]*?"version"\s*:\s*)"[^"]*"', rf'\g<1>"{version}"', new, count=1, flags=re.S)
            out.append((lock, text, new))
    return out


def main() -> int:
    version = read_version()
    stale = [(p, old, new) for p, old, new in targets(version) if old != new]
    if "--check" in sys.argv:
        for p, _, _ in stale:
            print(f"out of step with VERSION {version}: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p, _, new in stale:
        p.write_text(new, encoding="utf-8", newline="\n")
        print(f"updated {p.relative_to(ROOT)} -> {version}")
    if not stale:
        print(f"already at {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

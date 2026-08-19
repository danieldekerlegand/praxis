#!/usr/bin/env python3
"""One version, three manifests — the release-version parity check.

Praxis declares its version in three places that no build step derives from each other:

    src-tauri/tauri.conf.json   the app version, and the name of the .dmg tauri writes
    pyproject.toml              the Python core, which the bundle runs but does not contain
    ui/package.json             the frontend embedded into the shell

Nothing forces them to agree, so a release can ship a `Praxis_0.2.0_aarch64.dmg` around a
0.1.0 core. This says so — before the bundle is built (`scripts/bundle-macos.sh` runs it)
and on every PR that touches a manifest (`tests/test_packaging.py` asserts on it, which is
what puts it in CI's python job).

    scripts/check-versions.py [ROOT]      # ROOT defaults to the repo root

Exit 0 prints the agreed version. Exit 1 names every manifest and the version it declares,
so the message alone says which file to edit. (bundle-macos.sh turns that into its own
exit 2 — "refused before the build", the same code as its other pre-build refusals.)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MANIFESTS = ("src-tauri/tauri.conf.json", "pyproject.toml", "ui/package.json")


def _json_version(text: str) -> str | None:
    return json.loads(text).get("version")


def _toml_version(text: str) -> str | None:
    """`version` under `[project]`, read without tomllib — it lands in 3.11 and this
    repo supports 3.10, and a release check should not need a dependency to run."""
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
        elif section == "[project]":
            match = re.match(r"""version\s*=\s*["']([^"']+)["']""", stripped)
            if match:
                return match.group(1)
    return None


def declared(root: Path) -> dict[str, str]:
    """What each manifest says its version is — or why it could not be read."""
    out = {}
    for rel in MANIFESTS:
        path = root / rel
        try:
            text = path.read_text()
        except OSError:
            out[rel] = "(no such file)"
            continue
        try:
            version = _toml_version(text) if path.suffix == ".toml" else _json_version(text)
        except ValueError:
            out[rel] = "(unreadable)"
            continue
        out[rel] = version if version else '(no "version" field)'
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else ROOT
    found = declared(root)
    agreed = set(found.values())

    if len(agreed) == 1 and not next(iter(agreed)).startswith("("):
        print(f"version {agreed.pop()} in step across {', '.join(MANIFESTS)}")
        return 0

    width = max(len(rel) for rel in MANIFESTS)
    print("version: the manifests disagree — a release must carry one version.", file=sys.stderr)
    for rel, version in found.items():
        print(f"  {rel.ljust(width)}  {version}", file=sys.stderr)
    print("fix: set the same version in each file above, then re-run this check.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

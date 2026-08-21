#!/usr/bin/env python3
"""Run Praxis's nbgrader gate over a notebook tree."""

from __future__ import annotations

import sys
from pathlib import Path

from praxis.checks import nbgrader_validate


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv] or [Path("notebooks")]
    paths = sorted({path for root in roots for path in (
        [root] if root.is_file() else root.rglob("*.ipynb")
    ) if path.with_name(path.stem + ".checks.json").is_file()})
    failures = 0
    for path in paths:
        for failure in nbgrader_validate(path):
            print(f"{path}: {failure}", file=sys.stderr)
            failures += 1
    print(f"nbgrader validate: {len(paths)} notebooks, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

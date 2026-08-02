"""The completion gate Ralph must satisfy.

Semantics (so unfinished scaffolds never block finished work):
  - EVERY notebook must be valid nbformat — always enforced.
  - A NEW-curriculum notebook (domains 01-10) is graded strictly ONLY once its
    author flips `metadata.praxis.status` from "scaffold" to "complete":
    then it must drop all placeholders, keep the 8 rubric sections, be substantive,
    and (if runnable) carry >= 2 code cells. While still "scaffold" it's skipped.
  - A LEGACY notebook (domain 11, no Praxis metadata) is graded lightly once its
    placeholder template text is gone: no placeholder markers, and substantive size.
    While it still has template markers it's skipped (not yet finished).

So a Ralph task is "done" exactly when its notebook passes here; everything still
to-do is skipped, keeping the suite green for the tasks that ARE complete.

See docs/notebook-rubric.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NOTEBOOKS = sorted((ROOT / "notebooks").rglob("*.ipynb"))

from nbstatus import notebook_meta  # noqa: E402

PLACEHOLDER_MARKERS = (
    "todo",
    "provide description here",
    "add code here",
    "add benchmarking code",
    "[add architecture diagram here]",
    "[link]",
    "feature 1 | description",
    "- benefit 1",
    "study notebook — scaffold",
)

RUBRIC_SECTIONS = (
    "What & Why",
    "Mental Model",
    "Key Concepts",
    "Setup",
    "Worked Examples",
    "Gotchas",
    "When to Use",
    "Resources",
)


def _ids(paths):
    return [p.relative_to(ROOT / "notebooks").as_posix() for p in paths]


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _text(nb: dict) -> str:
    return "".join("".join(c.get("source", [])) for c in nb.get("cells", []))


def _is_new_curriculum(path: Path) -> bool:
    domain = path.relative_to(ROOT / "notebooks").parts[0]
    return domain != "11-devops-mlops-infra"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=_ids(NOTEBOOKS))
def test_valid_nbformat(path: Path):
    nbformat.read(str(path), as_version=4)  # raises on invalid


@pytest.mark.parametrize("path", NOTEBOOKS, ids=_ids(NOTEBOOKS))
def test_notebook_meets_rubric_when_done(path: Path):
    nb = _load(path)
    meta = notebook_meta(nb)
    text = _text(nb)
    low = text.lower()

    if _is_new_curriculum(path):
        # Graded only once the author declares completion.
        if meta.get("status") != "complete":
            pytest.skip("scaffold / in progress — not yet marked complete")
        bad = [m for m in PLACEHOLDER_MARKERS if m in low]
        assert not bad, f"placeholder text remains: {bad}"
        missing = [s for s in RUBRIC_SECTIONS if s.lower() not in low]
        assert not missing, f"missing rubric sections: {missing}"
        assert len(text) >= 4000, f"too thin ({len(text)} chars) — write a real refresher"
        if meta.get("runnable", True):
            code_cells = [c for c in nb["cells"] if c.get("cell_type") == "code"]
            assert len(code_cells) >= 2, "runnable notebook needs >= 2 code cells"
    else:
        # Legacy: skip while template markers remain; otherwise grade lightly.
        legacy_markers = ("provide description here", "add code here",
                          "feature 1 | description", "- benefit 1")
        if any(m in low for m in legacy_markers):
            pytest.skip("legacy template stub — not yet finished")
        assert len(text) >= 5000, f"legacy notebook too thin ({len(text)} chars)"

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

The strict checks themselves live in `praxis/rubric.py` — this file decides *which*
notebooks get graded, `gate_failures()` decides what "graded" means. The AI constructor
(praxis/construct.py) grades its own output with that same function before it is allowed
to write, so a constructed notebook cannot pass one bar and fail the other.

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
from praxis.rubric import gate_failures  # noqa: E402


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
        # Graded only once the author (or the constructor) declares completion.
        if meta.get("status") != "complete":
            pytest.skip("scaffold / in progress — not yet marked complete")
        failures = gate_failures(nb)
        assert not failures, "; ".join(failures)
    else:
        # Legacy: skip while template markers remain; otherwise grade lightly.
        legacy_markers = ("provide description here", "add code here",
                          "feature 1 | description", "- benefit 1")
        if any(m in low for m in legacy_markers):
            pytest.skip("legacy template stub — not yet finished")
        assert len(text) >= 5000, f"legacy notebook too thin ({len(text)} chars)"

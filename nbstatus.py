#!/usr/bin/env python3
"""Shared notebook status detection, used by the launcher, tests, and Ralph generator.

Three states:
  scaffold  - blank Praxis scaffold, or a legacy template with placeholder text
  partial   - has real content but is thin / still below the rubric bar
  complete  - substantive content, no placeholders, enough sections and code

This is a heuristic for the UI badge and for *selecting* which notebooks Ralph
should work on. The authoritative gate is tests/test_notebooks.py.
"""

from __future__ import annotations

import json
from pathlib import Path

# Placeholder markers left by the legacy generator/enhancer templates.
STUB_MARKERS = (
    "provide description here",
    "add code here",
    "feature 1 | description",
    "[add architecture diagram here]",
    "add benchmarking code",
    "- benefit 1",
    "this notebook provides practical examples and best practices",
)

REQUIRED_HINTS = ("## ", "import ", "```")  # cheap "has real structure" signals

# Notebooks carry their tutorial metadata under `metadata.praxis`. Notebooks
# authored before the ai-tutor -> Praxis rebrand used `metadata.ai_tutor`; that
# key is still read so an externally-authored legacy notebook keeps working.
META_KEY = "praxis"
LEGACY_META_KEY = "ai_tutor"


def notebook_meta(nb: dict) -> dict:
    """The Praxis metadata block of a notebook dict (legacy key as fallback)."""
    meta = nb.get("metadata", {})
    return meta.get(META_KEY) or meta.get(LEGACY_META_KEY) or {}


def _text(nb: dict) -> str:
    return "".join("".join(c.get("source", [])) for c in nb.get("cells", []))


def notebook_status(path: str | Path) -> tuple[str, dict]:
    """Return (status, metrics) for a notebook path."""
    path = Path(path)
    try:
        nb = json.loads(path.read_text())
    except Exception as exc:  # unreadable / invalid JSON
        return "error", {"error": str(exc)}
    return status_from_dict(nb)


def status_from_dict(nb: dict) -> tuple[str, dict]:
    """Return (status, metrics) for a notebook already in memory.

    The badge rules live here and only here; the constructor grades a notebook it has
    just written *before* saving it, so it needs the same call without a round trip
    through the filesystem.
    """
    meta = notebook_meta(nb)
    cells = nb.get("cells", [])
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    text = _text(nb)
    low = text.lower()
    chars = len(text)

    metrics = {
        "cells": len(cells),
        "code_cells": len(code_cells),
        "chars": chars,
        "runnable": meta.get("runnable", True),
        "recommended": meta.get("recommended", False),
    }

    # Explicit scaffold sentinel, or any legacy placeholder text.
    if meta.get("status") == "scaffold" or any(m in low for m in STUB_MARKERS):
        return "scaffold", metrics

    # Heuristic completeness for filled notebooks.
    has_structure = sum(h in text for h in REQUIRED_HINTS) >= 2
    runnable = metrics["runnable"]
    enough_code = (len(code_cells) >= 2) if runnable else True
    if chars >= 6000 and has_structure and enough_code:
        return "complete", metrics
    return "partial", metrics


BADGE = {"scaffold": "🔴", "partial": "🟡", "complete": "✅", "error": "⚠️"}

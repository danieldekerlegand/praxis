#!/usr/bin/env python3
"""One definition of "complete" — the rubric, as code.

`docs/notebook-rubric.md` is the prose; this is the machine-checkable half of it, and
the *only* place the thresholds live. Two callers, deliberately sharing one definition:

  - tests/test_notebooks.py grades a finished notebook with `gate_failures()`.
  - praxis/construct.py refuses to declare a notebook constructed unless
    `construction_failures()` comes back empty.

If the constructor's checks were a separate copy they would drift, and a drifted copy
is how an unfilled notebook gets flagged ✅. The construction bar is deliberately the
*stricter* of the two: it also demands the badge in nbstatus.py, real URLs under
Resources, and code cells that at least parse as Python. Existing hand-written
notebooks are held to `gate_failures()` alone, so tightening the construction bar
never retroactively fails the seed library.

Stdlib only — the construction core stays dependency-light.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nbstatus import notebook_meta, status_from_dict  # noqa: E402

# Scaffold and legacy-template text. Any of these surviving means nobody filled the
# notebook — "todo" is a substring match on purpose, so `TODO:` in any casing trips it.
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

# The eight sections of docs/notebook-rubric.md, matched case-insensitively as substrings
# so "## 1. What & Why" and "## What & Why" both count.
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

# The gate's floor. nbstatus.py wants 6000 before it badges ✅, so a constructed
# notebook has to clear that higher bar — see construction_failures().
MIN_CHARS = 4000
MIN_RESOURCE_URLS = 3

# A "real URL" is not one of these. The model reaches for them when it doesn't know
# the actual docs link, which is exactly the fabrication the rubric forbids.
PLACEHOLDER_URL_MARKERS = (
    "example.com",
    "example.org",
    "your-domain",
    "yourdomain",
    "localhost",
    "127.0.0.1",
    "url-here",
    "link-here",
    "...",
)

URL_RE = re.compile(r"https?://[^\s)\]>\"'`,]+")

# IPython line/cell magics and shell escapes are valid in a notebook and invalid to
# `compile()`, so they're blanked before the syntax check rather than failing it.
_MAGIC_RE = re.compile(r"^\s*[%!?]", re.MULTILINE)


def cell_source(cell: dict) -> str:
    """A cell's source, whether nbformat stored it as a string or a list of lines."""
    source = cell.get("source", "")
    return source if isinstance(source, str) else "".join(source)


def notebook_text(nb: dict) -> str:
    return "".join(cell_source(c) for c in nb.get("cells", []))


def code_cells(nb: dict) -> list[dict]:
    return [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]


def is_runnable(nb: dict) -> bool:
    return bool(notebook_meta(nb).get("runnable", True))


def gate_failures(nb: dict) -> list[str]:
    """What tests/test_notebooks.py asserts about a notebook declared complete.

    Empty list == passes the gate. Every entry is a sentence a human can act on, and
    the same sentences are fed back to the model when construction retries.
    """
    text = notebook_text(nb)
    low = text.lower()
    failures = []

    found = [m for m in PLACEHOLDER_MARKERS if m in low]
    if found:
        failures.append(f"placeholder text remains: {found}")

    missing = [s for s in RUBRIC_SECTIONS if s.lower() not in low]
    if missing:
        failures.append(f"missing rubric sections: {missing}")

    if len(text) < MIN_CHARS:
        failures.append(f"too thin ({len(text)} chars, need >= {MIN_CHARS})")

    if is_runnable(nb) and len(code_cells(nb)) < 2:
        failures.append(
            f"a runnable notebook needs >= 2 code cells (has {len(code_cells(nb))})"
        )

    return failures


def _resources_text(nb: dict) -> str:
    """Everything from the Resources heading to the end — where the links must be."""
    text = notebook_text(nb)
    match = re.search(r"#+\s*\d*\.?\s*Resources", text, re.IGNORECASE)
    return text[match.start():] if match else ""


def resource_url_failures(nb: dict) -> list[str]:
    """Resources must carry real links — the rubric's one un-fudgeable requirement."""
    urls = URL_RE.findall(_resources_text(nb))
    fake = [u for u in urls if any(m in u.lower() for m in PLACEHOLDER_URL_MARKERS)]
    failures = []
    if len(urls) < MIN_RESOURCE_URLS:
        failures.append(
            f"Resources needs >= {MIN_RESOURCE_URLS} real https:// links (found {len(urls)})"
        )
    if fake:
        failures.append(f"Resources holds placeholder URLs: {fake}")
    return failures


def code_syntax_failures(nb: dict) -> list[str]:
    """Every code cell must parse as Python — a cell that can't even compile never ran."""
    failures = []
    for i, cell in enumerate(code_cells(nb), 1):
        source = _MAGIC_RE.sub("#", cell_source(cell))
        try:
            compile(source, f"<code cell {i}>", "exec")
        except SyntaxError as exc:
            failures.append(f"code cell {i} is not valid Python: {exc.msg} (line {exc.lineno})")
    return failures


def construction_failures(nb: dict) -> list[str]:
    """The bar a *constructed* notebook must clear before it may be written to disk.

    The gate, plus the three things a model will otherwise fake: the ✅ badge (which
    wants real length and structure), real resource URLs, and code that parses.
    """
    failures = gate_failures(nb)

    status, _ = status_from_dict(nb)
    if status != "complete":
        failures.append(f"nbstatus reports {status!r}, not 'complete'")

    failures += resource_url_failures(nb)
    failures += code_syntax_failures(nb)
    return failures

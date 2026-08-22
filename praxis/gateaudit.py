#!/usr/bin/env python3
"""Gate quality: is a written gate actually asking the learner anything?

`praxis/backfill.py` writes gates at library scale, and every one of them already
cleared two bars before it landed: `checks.checkset_failures()` (the shipped write-path
grader, whose load-bearing half *runs* each `code` check's reference solution against
its own `test` in a subprocess) and `nbgrader validate` (band 84's authoritative gate on
the graded cells). This module is the third question, and it is deliberately the one
neither of those can answer.

**The residue.** `nbgrader validate` proves a graded cell is well-formed and that its
hidden tests execute against its solution. It cannot tell you that the question is
trivial, that the prompt gives its own answer away, or that the test asserts nothing
about the learner's answer. `checkset_failures` proves the set is *gradable*. Neither
proves it is *worth grading*. That gap is what an unattended batch introduces at scale —
a gate that technically validates and asks nothing real — and it is all this module
looks at. It re-implements no part of validate's wellformedness or execution checks; it
calls the shipped grader for that half rather than growing a parallel one.

Four failure modes, each measured rather than guessed:

  - **The answer is given away in the prompt** — a `choice` whose correct option is
    already spelled out in the question, or a `short` whose marking key is quoted back
    in it. Measured as word coverage of the key by the prompt, and (for `choice`)
    against how much the *distractors* share, so a question that simply reuses its own
    subject's vocabulary is not mistaken for one that hands over its answer.
  - **The notebook body already answers it verbatim** — a `short` whose `expected` is
    copied out of the prose the learner is reading, so it is passable by searching the
    page. Measured as word-shingle overlap against the notebook's *own* cells, with the
    Praxis-owned graded cells excluded (they carry the prompts, and a question is not
    evidence for itself).
  - **The test asserts nothing about the answer** — a `code` check whose `test` still
    passes when the learner writes nothing. This is the shipped subprocess check
    `run_code_check()` pointed the other way: generation proves the reference solution
    *passes*, and this proves the starter stub and an empty submission *fail*. A test
    that passes both directions is not a gate.
  - **The same question twice** — near-identical prompts inside one set, which is what a
    model does when it is asked for a question per section and has run out of things to
    ask. Measured as word overlap between every pair.

Every threshold here was chosen against the 24 hand-built seed gates, which is the bar a
backfilled gate has to hold: the worst genuine `choice` covers 43% of its answer's words
in the prompt (the rule fires at 80% *and* a wide margin over the distractors), the
worst genuine `short` shares 44% of its key with the notebook body (the rule fires at
70%), no genuine `code` test passes a stub or an empty submission (0 of 24), and the
most similar genuine pair of prompts overlaps 33% (the rule fires at 70%).

The sentences are written to be acted on, the same rule the constructor's grader
follows: they are what a repair prompt hands back to the model and what the UI shows.

CLI::

    python3 -m praxis.gateaudit                  audit every gate under notebooks/
    python3 -m praxis.gateaudit notebooks/12-model-evaluation
    python3 -m praxis.gateaudit --json           the machine-readable report
    python3 -m praxis.gateaudit --fast           skip the subprocess runs
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis.checks import (  # noqa: E402
    CHECKS_SUFFIX,
    checkset_failures,
    graded_cells,
    load_checks,
    run_code_check,
)

DEFAULT_NOTEBOOKS = ROOT / "notebooks"

# --- where each rule fires (see the module docstring for the measurements) ---

GIVEAWAY_COVERAGE = 0.8   # of the correct option's words, already in the prompt
GIVEAWAY_MARGIN = 0.3     # ...and this much more than the best distractor shares
KEY_IN_PROMPT = 0.5       # of a short answer's key, quoted back in its own question
KEY_IN_BODY = 0.7         # ...or copied out of the notebook the learner is reading
DUPLICATE_OVERLAP = 0.7   # shared words between two prompts in one set
SHINGLE = 6               # words per shingle when looking for copied prose

# Words that say nothing about *which* answer is meant, so counting them would make
# every question look like it quotes itself.
STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from has have how if in into is it
    its may not of on or that the their them then there these they this to was were
    what when where which while who why will with you your about after all also any
    been both each more most must no other over same should some such than through
    under until up use used using very we our i""".split()
)


def _words(text: object) -> list[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def _content(text: object) -> set[str]:
    """The words that carry the meaning — long enough, and not a stopword."""
    return {w for w in _words(text) if len(w) > 3 and w not in STOPWORDS}


def _shingles(text: object, size: int = SHINGLE) -> set[str]:
    """Overlapping runs of *size* words — how copied prose is recognised."""
    words = _words(text)
    if len(words) < size:
        return set()
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def _coverage(key: object, haystack: object) -> float:
    """The fraction of *key*'s meaningful words that already appear in *haystack*."""
    words = _content(key)
    if not words:
        return 0.0
    return len(words & _content(haystack)) / len(words)


def _quoted(key: object, haystack: object) -> float:
    """The fraction of *key*'s word-shingles that appear verbatim in *haystack*."""
    shingles = _shingles(key)
    if not shingles:
        return 0.0
    return len(shingles & _shingles(haystack)) / len(shingles)


def _overlap(left: object, right: object) -> float:
    """How much two texts say the same thing (Jaccard over meaningful words)."""
    a, b = _content(left), _content(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _pct(value: float) -> int:
    return round(100 * value)


def _where(check: dict) -> str:
    return str(check.get("id") or check.get("prompt", "")[:40])


def body_text(nb: dict) -> str:
    """The notebook's own prose — everything except the cells a gate wrote into it.

    `annotate_notebook()` publishes each check's prompt as a cell, so a gated notebook
    contains its own questions. Counting those as "the body already says it" would make
    every gate look like it copied itself out of the page.
    """
    owned = {id(cell) for cell in graded_cells(nb)}
    return "".join(
        "".join(cell.get("source", []))
        for cell in nb.get("cells", [])
        if id(cell) not in owned
    )


# --- the residue, one check at a time ---------------------------------------


def quality_failures(
    check: dict, *, notebook: str = "", runnable: bool = True, verify_code: bool = True
) -> list[str]:
    """What is trivial or given away about one check. Empty == it asks something.

    Says nothing about whether the check is *gradable* — that is
    `checks.check_failures()`, and this is only ever run alongside it.
    """
    if not isinstance(check, dict):
        return []
    where = _where(check)
    prompt = check.get("prompt", "")
    kind = check.get("kind")
    failures: list[str] = []

    if kind == "choice":
        options = [o for o in (check.get("options") or []) if isinstance(o, str)]
        answer = check.get("answer", -1)
        if isinstance(answer, int) and 0 <= answer < len(options):
            correct = options[answer]
            distractors = [o for i, o in enumerate(options) if i != answer]
            covered = _coverage(correct, prompt)
            best_distractor = max((_coverage(o, prompt) for o in distractors), default=0.0)
            if covered >= GIVEAWAY_COVERAGE and covered - best_distractor >= GIVEAWAY_MARGIN:
                failures.append(
                    f"{where}: the question gives its own answer away — {_pct(covered)}% "
                    f"of the correct option's words are already in the prompt, against "
                    f"{_pct(best_distractor)}% for the closest distractor, so it can be "
                    "picked by matching wording. Ask what the learner has to work out, "
                    "and do not restate the answer in the question."
                )

    elif kind == "short":
        expected = check.get("expected", "")
        quoted = _quoted(expected, prompt)
        if quoted >= KEY_IN_PROMPT:
            failures.append(
                f"{where}: the question contains its own marking key — {_pct(quoted)}% "
                "of 'expected' is quoted back in the prompt, so a learner can pass by "
                "repeating the question. Ask for the reasoning and keep the key in "
                "'expected'."
            )
        if notebook:
            copied = _quoted(expected, notebook)
            if copied >= KEY_IN_BODY:
                failures.append(
                    f"{where}: the answer is copied out of the notebook — {_pct(copied)}% "
                    "of 'expected' appears verbatim in the prose the learner is reading, "
                    "so it is passable by searching the page. Ask the learner to apply "
                    "the idea to a case the notebook does not work through."
                )

    elif kind == "code" and verify_code and runnable and "assert" in check.get("test", ""):
        starter = check.get("starter", "")
        passed_empty, _ = run_code_check(check, "")
        if passed_empty:
            failures.append(
                f"{where}: the test passes an empty submission — it asserts nothing "
                "about the learner's answer, so any answer is a pass. Assert the "
                "behaviour the prompt asks for, on inputs the starter cannot satisfy."
            )
        elif starter.strip():
            passed_starter, _ = run_code_check(check, starter)
            if passed_starter:
                failures.append(
                    f"{where}: the test passes the starter stub unchanged — the learner "
                    "is graded on code they were given, not code they wrote. Assert the "
                    "behaviour the prompt asks for, on inputs the starter cannot satisfy."
                )

    return failures


def duplicate_failures(checks: list[dict]) -> list[str]:
    """Pairs of questions inside one set that ask the same thing twice."""
    usable = [c for c in checks if isinstance(c, dict) and c.get("prompt")]
    failures = []
    for left, right in itertools.combinations(usable, 2):
        shared = _overlap(left.get("prompt"), right.get("prompt"))
        if shared >= DUPLICATE_OVERLAP:
            failures.append(
                f"{_where(left)} and {_where(right)}: these two questions are "
                f"near-identical ({_pct(shared)}% of their words are shared"
                f"{'' if left.get('section') == right.get('section') else ', across sections'}"
                f") — one of them tests nothing the other does not. Replace it with a "
                "question about something else the section teaches."
            )
    return failures


def set_quality_failures(
    doc: dict, *, notebook: str = "", verify_code: bool = True
) -> list[str]:
    """The whole residue for one stored set — per check, then across the set.

    `notebook` is the notebook's own body text (`body_text()`); without it the
    copied-out-of-the-page rule simply does not run, so a caller that has no notebook
    to hand still gets every other rule.
    """
    if not isinstance(doc, dict):
        return []
    checks = doc.get("checks")
    if not isinstance(checks, list):
        return []
    runnable = bool(doc.get("runnable", True))
    failures: list[str] = []
    for check in checks:
        failures += quality_failures(
            check, notebook=notebook, runnable=runnable, verify_code=verify_code
        )
    return failures + duplicate_failures(checks)


# --- auditing what is on disk -----------------------------------------------


def notebook_for_checks(path: str | Path) -> Path:
    """The notebook a `<slug>.checks.json` sits beside — `checks_path()` reversed."""
    path = Path(path)
    return path.with_name(path.name[: -len(CHECKS_SUFFIX)] + ".ipynb")


def _read_notebook(path: Path) -> dict | None:
    try:
        nb = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return nb if isinstance(nb, dict) else None


def audit_checkset(
    path: str | Path, *, root: str | Path | None = None, verify_code: bool = True
) -> dict[str, Any]:
    """Audit one gate without touching it.

    Both halves are reported separately and never merged into one verdict: the shipped
    write-path grader's sentences (`checkset_failures`, which is what generation
    enforced) and this module's residue. A gate can be perfectly gradable and still be
    flagged, which is the entire point of the band.
    """
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    doc = load_checks(path)
    if doc is None:
        return {
            "checks": relative,
            "slug": path.name[: -len(CHECKS_SUFFIX)],
            "notebook": None,
            "status": "unreadable",
            "checkset_failures": ["the checks file does not hold a JSON object"],
            "quality_failures": [],
            "findings": ["the checks file does not hold a JSON object"],
            "counts": {},
        }

    notebook_path = notebook_for_checks(path)
    nb = _read_notebook(notebook_path)
    gradable = checkset_failures(doc, verify_code=verify_code)
    residue = set_quality_failures(
        doc,
        notebook=body_text(nb) if nb else "",
        verify_code=verify_code,
    )
    checks = [c for c in (doc.get("checks") or []) if isinstance(c, dict)]
    return {
        "checks": relative,
        "slug": str(doc.get("slug") or path.name[: -len(CHECKS_SUFFIX)]),
        "notebook": (
            notebook_path.relative_to(root).as_posix()
            if nb and notebook_path.is_relative_to(root) else
            (notebook_path.as_posix() if nb else None)
        ),
        "status": "flagged" if (gradable or residue) else "healthy",
        "checkset_failures": gradable,
        "quality_failures": residue,
        "findings": gradable + residue,
        "counts": {
            kind: sum(1 for c in checks if c.get("kind") == kind)
            for kind in ("choice", "code", "short")
        },
    }


def audit_gates(
    root: str | Path = DEFAULT_NOTEBOOKS, *, verify_code: bool = True
) -> dict[str, Any]:
    """Audit every gate below *root* (or the single sidecar *root* names)."""
    root = Path(root)
    if root.is_file():
        paths, base = [root], root.parent
    else:
        paths, base = sorted(root.rglob(f"*{CHECKS_SUFFIX}")), root
    reports = [audit_checkset(p, root=base, verify_code=verify_code) for p in paths]
    flagged = [r for r in reports if r["status"] != "healthy"]
    return {
        "root": str(root),
        "gates": len(reports),
        "flagged": len(flagged),
        "checks": sum(sum(r["counts"].values()) for r in reports),
        "reports": reports,
    }


def render(report: dict) -> str:
    """The report as text — the flagged gates and why, then the count."""
    lines = []
    for item in report["reports"]:
        if item["status"] == "healthy":
            continue
        lines.append(item["checks"])
        lines += [f"  - {finding}" for finding in item["findings"]]
    lines.append("")
    lines.append(
        f"audited {report['gates']} gates ({report['checks']} checks); "
        f"{report['flagged']} flagged"
    )
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Audit written gates for trivial or given-away questions"
    )
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_NOTEBOOKS)
    parser.add_argument(
        "--fast", action="store_true",
        help="skip the subprocess runs (the structural half only)",
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = parser.parse_args(argv)
    report = audit_gates(args.root, verify_code=not args.fast)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render(report))
    return 1 if report["flagged"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))

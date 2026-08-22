#!/usr/bin/env python3
"""The gates written before the bar existed: re-audit them, regenerate by policy.

`checks.checkset_failures()` was tightened to reject a trivial or given-away gate on
the write path — but only from that moment on. The cheap load path deliberately runs
neither the subprocess verification nor the triviality rules (`quality` follows
`verify_code`), which is what keeps an already-gated notebook *skipped rather than
silently re-judged*. So every gate already on disk — the shipped seeds, and whatever a
79 backfill batch wrote before this band merged — has never been measured against the
bar it would have to clear today. This module is that measurement, and the one explicit
way to act on it.

**Which gates predate the bar is measured, not recorded.** No flag is written into a
checkset saying which grader passed it: the write path now rejects a set that fails the
tightened bar, so a gate on disk that fails it *is* one written before the tightening —
by construction, and without a marker anyone could set. That is the same reason
`progress.py` re-derives an unlock instead of storing one.

**The grader is the shipped one, called the way the write path calls it.** One call to
`checkset_failures(doc, verify_code=True, notebook=body_text(nb))` — quality on, because
it follows `verify_code` — so what this reports is exactly "would the write path accept
this set today?", down to the sentence. `praxis.gateaudit` splits the two halves apart
for its report; this deliberately does not, because a single verdict is the question
here. Neither module owns a rule the write path does not.

Two outcomes, the vocabulary `praxis/refresh.py` already uses for the seed library:

1. **FLAGGED-FOR-HUMAN** is the default, and a re-audit *writes nothing*. The gate that
   no longer meets the bar stays exactly where it is, with the grader's own sentences
   naming what is wrong with it. An already-gated notebook is skipped, not rewritten —
   the same rule the backfill and the constructor hold.
2. **FORCE-REGENERATE** is an explicit, per-notebook opt-in that hands the topic to the
   shipped write path (`checks.generate_checks(force=True)` — grade, `nbgrader
   validate`, then write). That path cannot write a set that fails the tightened bar, so
   a regeneration the model gets wrong leaves the existing gate in place: the notebook
   keeps the gate it had rather than being left ungated by an attempt to improve it.

A gate that still holds the bar is **HOLDS**, and is never a regeneration target even
when `force=True` — the same rule `refresh.refresh_notebook()` applies to a healthy
seed, and what makes an unattended re-audit cost no model call.

CLI::

    python3 -m praxis.regate                             re-audit every gate under notebooks/
    python3 -m praxis.regate notebooks/12-model-evaluation
    python3 -m praxis.regate --fast                      skip the subprocess runs
    python3 -m praxis.regate notebooks/a/b.checks.json --force
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import CurriculumError  # noqa: E402
from praxis.checks import (  # noqa: E402
    CHECKS_SUFFIX,
    ChecksResult,
    checkset_failures,
    load_checks,
)
from praxis.gateaudit import body_text, notebook_for_checks  # noqa: E402

DEFAULT_NOTEBOOKS = ROOT / "notebooks"

HOLDS = "HOLDS"
FLAGGED_FOR_HUMAN = "FLAGGED-FOR-HUMAN"
FORCE_REGENERATE = "FORCE-REGENERATE"


@dataclass(frozen=True)
class RegateResult:
    """The auditable decision made for one gate already on disk."""

    checks: str
    slug: str
    notebook: str | None
    outcome: str
    failures: tuple[str, ...] = ()
    generation: ChecksResult | None = None

    @property
    def ok(self) -> bool:
        """Whether the notebook is left holding a gate that meets today's bar."""
        if self.outcome == HOLDS:
            return True
        return (
            self.outcome == FORCE_REGENERATE
            and self.generation is not None
            and self.generation.status == "generated"
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "checks": self.checks,
            "slug": self.slug,
            "notebook": self.notebook,
            "outcome": self.outcome,
            "failures": list(self.failures),
        }
        if self.generation is not None:
            result["generation"] = {
                "status": self.generation.status,
                "attempts": self.generation.attempts,
                "count": self.generation.count,
                "detail": self.generation.detail,
                "failures": list(self.generation.failures),
            }
        return result

    def summary(self) -> str:
        mark = {HOLDS: "•", FLAGGED_FOR_HUMAN: "⚠️", FORCE_REGENERATE: "✍️"}[self.outcome]
        return f"{mark} {self.outcome}: {self.checks}"


def _read_notebook(path: Path) -> dict | None:
    try:
        nb = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return nb if isinstance(nb, dict) else None


def bar_failures(doc: dict, nb: dict | None = None, *, verify_code: bool = True) -> list[str]:
    """What the write path would say about this set today — the tightened grader.

    One call to the shipped `checkset_failures`, with `quality` left to follow
    `verify_code`, so the gradability half and the triviality half are the same two
    halves generation enforces. `nb` supplies the page the copied-out-of-the-notebook
    rule measures against; without it that one rule does not run.
    """
    return checkset_failures(
        doc, verify_code=verify_code, notebook=body_text(nb) if nb else ""
    )


def reaudit_gate(
    path: str | Path, *, root: str | Path | None = None, verify_code: bool = True
) -> RegateResult:
    """Measure one gate on disk against the tightened bar, writing nothing."""
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    slug = path.name[: -len(CHECKS_SUFFIX)] if path.name.endswith(CHECKS_SUFFIX) else path.stem
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()

    doc = load_checks(path)
    if doc is None:
        return RegateResult(
            checks=relative, slug=slug, notebook=None, outcome=FLAGGED_FOR_HUMAN,
            failures=("the checks file does not hold a JSON object",),
        )

    notebook_path = notebook_for_checks(path)
    nb = _read_notebook(notebook_path)
    notebook = None
    if nb is not None:
        notebook = (
            notebook_path.relative_to(root).as_posix()
            if notebook_path.is_relative_to(root) else notebook_path.as_posix()
        )

    failures = bar_failures(doc, nb, verify_code=verify_code)
    return RegateResult(
        checks=relative, slug=str(doc.get("slug") or slug), notebook=notebook,
        outcome=HOLDS if not failures else FLAGGED_FOR_HUMAN,
        failures=tuple(failures),
    )


def regate_gate(
    path: str | Path,
    *,
    force: bool = False,
    root: str | Path | None = None,
    verify_code: bool = True,
    **generate_kwargs: Any,
) -> RegateResult:
    """Re-audit one gate and, only on an explicit `force`, regenerate that one.

    `force` is keyword-only and per-gate on purpose. A gate that still holds the bar is
    never a regeneration target even with it, and a flagged one is regenerated through
    the shipped write path — which grades and validates before it writes, so a candidate
    that fails the tightened bar leaves the existing gate byte-identical rather than
    stripping the notebook of the gate it had.
    """
    result = reaudit_gate(path, root=root, verify_code=verify_code)
    if not force or result.outcome != FLAGGED_FOR_HUMAN:
        return result

    path = Path(path)
    notebook_path = notebook_for_checks(path)
    nb = _read_notebook(notebook_path)
    if nb is None:
        return RegateResult(
            checks=result.checks, slug=result.slug, notebook=result.notebook,
            outcome=FLAGGED_FOR_HUMAN,
            failures=result.failures + (
                f"there is no notebook at {notebook_path} to write a new gate against",
            ),
        )

    from praxis.checks import generate_checks  # the one write path, imported where used
    from praxis.construct import topic_for_path

    try:
        domain, topic, subject = topic_for_path(notebook_path)
    except CurriculumError as exc:
        return RegateResult(
            checks=result.checks, slug=result.slug, notebook=result.notebook,
            outcome=FLAGGED_FOR_HUMAN, failures=result.failures + (str(exc),),
        )

    generate_kwargs.setdefault("subject", subject)
    generation = generate_checks(
        domain, topic, notebook=nb, force=True, **generate_kwargs
    )
    return RegateResult(
        checks=result.checks, slug=result.slug, notebook=result.notebook,
        outcome=FORCE_REGENERATE, failures=result.failures, generation=generation,
    )


def reaudit_gates(
    root: str | Path = DEFAULT_NOTEBOOKS, *, verify_code: bool = True
) -> dict[str, Any]:
    """Re-audit every gate below *root* (or the single sidecar *root* names)."""
    root = Path(root)
    if root.is_file():
        paths, base = [root], root.parent
    else:
        paths, base = sorted(root.rglob(f"*{CHECKS_SUFFIX}")), root
    results = [reaudit_gate(p, root=base, verify_code=verify_code) for p in paths]
    flagged = [r for r in results if r.outcome != HOLDS]
    return {
        "root": str(root),
        "gates": len(results),
        "holds": len(results) - len(flagged),
        "flagged": len(flagged),
        "results": results,
    }


def render(report: dict) -> str:
    """The flagged gates and the grader's sentences, then the count."""
    lines = []
    for result in report["results"]:
        if result.outcome == HOLDS:
            continue
        lines.append(result.checks)
        lines += [f"  - {failure}" for failure in result.failures]
    lines.append("")
    lines.append(
        f"re-audited {report['gates']} gates against the tightened bar; "
        f"{report['holds']} hold, {report['flagged']} flagged for regeneration"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-audit gates written before the tightened bar; regenerate by policy"
    )
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_NOTEBOOKS)
    parser.add_argument(
        "--force", action="store_true",
        help="opt in to regenerating one flagged gate (one sidecar path only)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="skip the subprocess runs (the structural half of the bar only)",
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = parser.parse_args(argv)
    verify_code = not args.fast

    if args.force:
        if not args.root.is_file():
            parser.error("--force takes one <slug>.checks.json path, never a directory")
        result = regate_gate(args.root, force=True, verify_code=verify_code)
        if args.json:
            json.dump(result.as_dict(), sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(result.summary())
            for failure in result.failures:
                print(f"  - {failure}")
            if result.generation is not None:
                print(result.generation.summary())
        return 0 if result.ok else 1

    report = reaudit_gates(args.root, verify_code=verify_code)
    if args.json:
        json.dump(
            {**report, "results": [r.as_dict() for r in report["results"]]},
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(render(report))
    return 1 if report["flagged"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

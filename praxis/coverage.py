#!/usr/bin/env python3
"""How much of the library actually gates — overall, and domain by domain.

This is the honest headline of the gating program, and the number it starts from is not
flattering: **24 of 245** seed notebooks carry a gate today, so praxis's differentiating
feature is largely unshipped until `praxis/backfill.py` has run. A tracker exists so that
sentence stays a measurement rather than a claim.

Nothing here scans the library. The report is a **fold over the topic rows the launcher
already builds** (`launcher.app.build_model`), because a second scan is a second
definition of "gated" and the two would drift the first time one of them was tightened.
A row counts toward coverage when both halves of the gate are on disk:

  - `gated` — an answer key `learner_check()` can grade against, folded in by
    `progress.module_gates()`; this is the half that actually locks the next topic.
  - `graded` — the nbgrader graded cells in the notebook itself (decision D10 / band 84),
    folded in by `launcher.app._gated()` off `checks.graded_cells()`.

That conjunction is `backfill.is_gated()` restated on the view model, deliberately: the
batch that writes gates and the report that counts them must not disagree about which
notebooks are done. A sidecar with no cells is a half-migrated gate and is counted as
ungated — which is what puts it back in the backfill's queue instead of hiding it.

**The per-domain breakdown is the primary figure.** `library_targets()` orders a backfill
breadth-first across all 14 domains precisely because coverage everywhere is what the
gate is worth to a learner, and an overall fraction hides eleven empty domains behind
three full ones. `render()` therefore prints the domains first and the overall line last.

No number here is ever stored. Every fraction is recomputed from what is on disk at the
moment it is asked for, so the report cannot claim a gate the library does not have.

In the app it is one more field on the view model, not a second source of truth:
`build_model()` folds this report onto `/api/library` as `coverage` (and each domain's
own fraction onto its row as `covered`), so a resumed backfill's new gates show up on
the next library refetch with no extra scan and no extra poll. The UI renders those
numbers and computes none of them.

CLI:
    python3 -m praxis.coverage           the shipped library, per domain then overall
    python3 -m praxis.coverage --json    the same report, as the app receives it
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def is_gated(row: dict) -> bool:
    """Whether one library row carries a gate — both halves, or it isn't one.

    `backfill.is_gated()` asks the same question of the filesystem; this asks it of the
    view model the app serves, so the tracker's number and the app's behaviour are the
    same fact read at two altitudes.
    """
    return bool(row.get("gated")) and bool(row.get("graded"))


def domain_coverage(domain: dict) -> dict:
    """One domain's fraction: how many of its notebooks a learner meets a gate in."""
    topics = domain.get("topics") or []
    gated = sum(1 for row in topics if is_gated(row))
    total = len(topics)
    return {
        "dir": domain.get("dir", ""),
        "name": domain.get("name") or domain.get("title", ""),
        "title": domain.get("title", ""),
        "gated": gated,
        "total": total,
        "complete": sum(1 for row in topics if row.get("status") == "complete"),
        "pct": _pct(gated, total),
    }


def coverage_report(domains: Sequence[dict]) -> dict:
    """Gated coverage per domain (the primary figure) and overall, off library rows.

    `domains` is `build_model()["domains"]` — or anything shaped like it, which is what
    lets the arithmetic be tested without a filesystem. The overall fraction is the sum
    of the per-domain ones and never a separately counted number, so the headline and
    the breakdown cannot disagree.
    """
    per_domain = [domain_coverage(d) for d in domains]
    gated = sum(d["gated"] for d in per_domain)
    total = sum(d["total"] for d in per_domain)
    return {
        "domains": per_domain,
        "gated": gated,
        "total": total,
        "complete": sum(d["complete"] for d in per_domain),
        "pct": _pct(gated, total),
        # Breadth, the thing a round-robin backfill is actually moving.
        "domainsGated": sum(1 for d in per_domain if d["gated"]),
        "domainsTotal": len(per_domain),
    }


def library_report(learner: str | None = None) -> dict:
    """The shipped library's coverage, right now.

    The one place this module reaches up to the launcher, and it does it inside the
    function on purpose: the arithmetic above stays importable (and testable) with no
    launch extra installed, and the view model keeps living in exactly one place.

    `build_model()` already folds this report onto the library it serves — the same key
    `/api/library` carries — so the CLI below and the in-app tracker print one number
    computed once, not two that agree by luck.
    """
    from launcher.app import build_model  # noqa: PLC0415  (the adapter, not a dependency)
    from praxis.progress import DEFAULT_LEARNER

    return build_model(learner or DEFAULT_LEARNER)["coverage"]


def render(report: dict) -> str:
    """The report as text — per-domain first, because breadth is what is being moved."""
    rows = report.get("domains") or []
    width = max((len(d["name"]) for d in rows), default=0)
    lines = [f"{d['name']:<{width}}  {d['gated']:>3}/{d['total']:<3} {d['pct']:>3}%"
             for d in rows]
    lines.append("")
    lines.append(f"{report['gated']}/{report['total']} notebooks gated "
                 f"({report['pct']}%), in {report['domainsGated']} of "
                 f"{report['domainsTotal']} domains")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    report = library_report()
    print(json.dumps(report, indent=2) if "--json" in argv else render(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))

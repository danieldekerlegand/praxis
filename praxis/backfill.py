"""Gating backfill: drive the ✅-but-ungated library to gated, one domain at a time.

This invents no gating primitive. It is a *selector* in front of the shipped batch loop
— `construct_each` → `construct_topic(..., checks=True)` → `praxis/checks.py` over
`GATED_SECTIONS` — so the anti-fabrication bar a backfilled notebook clears is exactly
the one the constructor already enforces: a set is written only when `checkset_failures`
passes (the reference `solution` run against its own `test` in a subprocess) and
`nbgrader validate` accepts the annotated notebook. A gate that fails either is not
written, and the notebook stays ungated rather than gaining a fake one.

What this module adds is *which* notebooks to hand that loop, and the two rules that
make an unattended, resumable run safe:

- an already-gated topic is **skipped, not rewritten** — `needs_checks()` re-expressed
  against the nbgrader cell schema, so "gated" means the answer key loads clean *and*
  the notebook carries the graded cells;
- a notebook that is not yet ✅ is **left for construction**, never force-gated: checks
  written against a scaffold would ask questions about prose nobody has written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import (  # noqa: E402
    CurriculumError,
    Domain,
    Subject,
    Topic,
    domain_path,
    topic_path,
)
from nbstatus import notebook_status  # noqa: E402
from praxis.checks import graded_cells, needs_checks  # noqa: E402
from praxis.construct import (  # noqa: E402
    ConstructionResult,
    Target,
    construct_each,
    topic_for_path,
)


def _notebook(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def is_complete(domain: Domain, topic: Topic) -> bool:
    """Whether this topic's notebook is ✅ — the only kind worth writing a gate for."""
    return notebook_status(topic_path(domain, topic))[0] == "complete"


def is_gated(domain: Domain, topic: Topic) -> bool:
    """`needs_checks()` re-expressed against the nbgrader schema.

    A topic counts as gated only when both halves are on disk: the answer key that
    `learner_check()` grades against, and the graded cells in the notebook itself. A
    sidecar with no cells is a half-migrated gate, not a gate — so the backfill picks
    it up rather than reporting coverage it does not have.
    """
    if needs_checks(domain, topic):
        return False
    nb = _notebook(topic_path(domain, topic))
    return nb is not None and bool(graded_cells(nb))


def domain_targets(domain: Domain, *, subject: Subject | None = None) -> list[Target]:
    """Every notebook that exists under one domain, as construct_each targets.

    A `filesystem` domain enumerates no topics and nests, so its notebooks are resolved
    the way the constructor already resolves an off-manifest path — `topic_for_path()`
    synthesizes the Domain/Topic, and `topic_path()` lands back on that exact file.
    """
    if domain.source != "filesystem":
        return [(domain, topic, subject) for topic in domain.topics
                if topic_path(domain, topic).is_file()]
    targets: list[Target] = []
    for path in sorted(domain_path(domain).rglob("*.ipynb")):
        if ".ipynb_checkpoints" in path.parts:
            continue
        try:
            targets.append(topic_for_path(path))
        except CurriculumError:
            continue  # an unreadable notebook is construction's problem, not the gate's
    return targets


def backfill_targets(domain: Domain, *, subject: Subject | None = None) -> list[Target]:
    """The ungated ✅ topics of one domain, in library order."""
    return [
        (dom, topic, subj) for dom, topic, subj in domain_targets(domain, subject=subject)
        if is_complete(dom, topic) and not is_gated(dom, topic)
    ]


def backfill_domain(
    domain: Domain,
    *,
    subject: Subject | None = None,
    limit: int | None = None,
    **kwargs,
) -> list[ConstructionResult]:
    """Gate one domain's ungated ✅ notebooks, in curriculum order.

    `limit` is the depth knob a breadth-first pass turns down: the first `limit` ungated
    topics of this domain, so every domain can gain a gate before any one is finished.
    Resumable and safe to re-invoke — a second run selects nothing it already gated, so
    it costs no model call and rewrites no notebook.
    """
    targets = backfill_targets(domain, subject=subject)
    if limit is not None:
        targets = targets[:max(0, limit)]
    kwargs.setdefault("checks", True)
    return construct_each(targets, **kwargs)

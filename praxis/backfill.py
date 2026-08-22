"""Gating backfill: drive the ✅-but-ungated library to gated, in domain-sized batches.

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

`backfill_domain` runs one domain; `backfill_library` runs the whole shipped manifest
and is the entry point a batch uses. The difference between them is only the **order**:
the library batch interleaves the domains rather than draining one at a time, because
coverage across all 14 is what the gate is worth — see `library_targets`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import curriculum  # noqa: E402  (module, not `from ... import DOMAINS`: read live)
from curriculum import (  # noqa: E402
    CurriculumError,
    Domain,
    Subject,
    Topic,
    all_subjects,
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


# --- the whole library, breadth-first ---------------------------------------


def library_domains(*, subjects: bool = False) -> list[tuple[Domain, Subject | None]]:
    """Every domain a batch can reach, paired with the curriculum it belongs to.

    The order is `curriculum.DOMAINS`' own — the numbered seed domains, 01 through 15
    — read live rather than bound at import, the way `promote`/`library_index` read it,
    so a domain appended to the manifest joins the batch with no change here. Generated
    subjects are off by default: their notebooks reach the same gate through
    `construct_subject`, and a backfill of the shipped library must not walk into the
    user's data.
    """
    domains: list[tuple[Domain, Subject | None]] = [(d, None) for d in curriculum.DOMAINS]
    if subjects:
        domains += [(m, s) for s in all_subjects() for m in s.modules]
    return domains


def library_targets(
    domains: Sequence[tuple[Domain, Subject | None]] | None = None,
    *,
    depth: int = 1,
    limit: int | None = None,
) -> list[Target]:
    """The library's ungated ✅ topics, ordered **breadth-first across domains**.

    Each domain's own backlog stays in curriculum order, but the batch takes only
    `depth` of them before moving to the next domain and comes back for the next
    `depth` on the following round. So a run that is interrupted — or capped with
    `limit` — leaves every domain a little gated rather than three domains finished
    and eleven with nothing, which is the coverage this band is measured on.

    `depth` is the only knob between the two extremes: 1 is a pure round robin, and a
    number larger than the biggest domain's backlog degenerates to domain-at-a-time.
    """
    if domains is None:
        domains = library_domains()
    queues = [backfill_targets(domain, subject=subject) for domain, subject in domains]
    ordered: list[Target] = []
    step = max(1, depth)
    for start in range(0, max((len(q) for q in queues), default=0), step):
        for queue in queues:
            ordered.extend(queue[start:start + step])
    return ordered if limit is None else ordered[:max(0, limit)]


def backfill_library(
    domains: Sequence[tuple[Domain, Subject | None]] | None = None,
    *,
    depth: int = 1,
    limit: int | None = None,
    **kwargs,
) -> list[ConstructionResult]:
    """Gate the library's ungated ✅ notebooks, breadth-first across its domains.

    A one-liner over `construct_each`, exactly like `construct_domain` and
    `construct_subject` — which is where every property an unattended run needs comes
    from: a topic gated by an earlier batch is not selected at all, one the model could
    not make gradable comes back "failed" instead of stranding the rest, and a pass
    with nothing left to do resolves no client and so costs no key.
    """
    kwargs.setdefault("checks", True)
    return construct_each(library_targets(domains, depth=depth, limit=limit), **kwargs)


def coverage(
    domains: Sequence[tuple[Domain, Subject | None]] | None = None,
) -> list[tuple[Domain, int, int, int]]:
    """Per-domain `(domain, gated, complete, total)` — what a breadth pass moves."""
    if domains is None:
        domains = library_domains()
    counted = []
    for domain, subject in domains:
        targets = domain_targets(domain, subject=subject)
        complete = [(d, t) for d, t, _ in targets if is_complete(d, t)]
        counted.append((domain, sum(is_gated(d, t) for d, t in complete),
                        len(complete), len(targets)))
    return counted


# --- CLI --------------------------------------------------------------------


def _domains_for(dirs: Sequence[str]) -> list[tuple[Domain, Subject | None]]:
    """Resolve the named seed domains, or the whole library when none are named."""
    if not dirs:
        return library_domains()
    chosen = []
    for name in dirs:
        domain = curriculum.domain_by_dir(name)
        if domain is None:
            raise CurriculumError(
                f"no seed domain '{name}' — its id is the directory under notebooks/, "
                f"e.g. {curriculum.DOMAINS[0].dir}"
            )
        chosen.append((domain, None))
    return chosen


def main(argv: list[str] | None = None) -> int:
    """Run the backfill from a shell — the entry point a Chief tasklist drives.

    `--list` is the half that costs nothing: it prints the selection and stops, so a
    batch's plan (and a generated tasklist's warmup) can be read with no key configured
    and no model call made.
    """
    import argparse  # noqa: PLC0415  (a CLI convenience, not an import-time dependency)

    parser = argparse.ArgumentParser(
        description="Gate the ✅-but-ungated notebooks of one domain, or of the library"
    )
    parser.add_argument("domains", nargs="*", metavar="DIR",
                        help="seed domain directories (default: the whole library)")
    parser.add_argument("--list", action="store_true",
                        help="print the selection and exit — no model call, no key")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of topics")
    parser.add_argument("--depth", type=int, default=1,
                        help="topics per domain per round when running the library (default 1)")
    args = parser.parse_args(argv)

    try:
        domains = _domains_for(args.domains)
    except CurriculumError as exc:
        print(f"praxis.backfill: {exc}", file=sys.stderr)
        return 2

    targets = library_targets(domains, depth=max(1, args.depth), limit=args.limit)
    if args.list:
        for domain, gated, complete, total in coverage(domains):
            print(f"{domain.dir:<28} {complete - gated:>3} ungated of {complete:>3} ✅ "
                  f"({total} notebooks)")
        print(f"\n{len(targets)} topics selected, in batch order:")
        for domain, topic, _ in targets:
            print(f"  {domain.dir}/{topic.slug}.ipynb")
        return 0

    results = construct_each(targets, checks=True)
    failed = 0
    for result in results:
        print(result.summary())
        if not result.checks_ok:
            for failure in result.checks.failures or (result.checks.detail,):
                print(f"    - checks: {failure}", file=sys.stderr)
            failed += 1
        elif not result.ok:
            for failure in result.failures:
                print(f"    - {failure}", file=sys.stderr)
            failed += 1
    print(f"\n{len(results) - failed} of {len(results)} topics gated")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

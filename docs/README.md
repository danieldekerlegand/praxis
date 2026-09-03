# praxis documentation

> **Status:** Current · **Updated:** 2026-09-03 · **Owner:** praxis

**praxis** constructs interactive, gated notebook tutorials for any user-defined subject — agents fill notebooks to a rubric, with AI-built knowledge checks gating progression. A standalone Tauri product: **BYO-key**, with agora optional rather than required.

The map. Structured per the ecosystem documentation standard
(`rosetta/docs/reference/documentation-standard.md` — a private repo, so it is cited as
prose rather than as a link that would be broken for every outside reader) —
**a document not linked here does not exist**.

## Reference

*information-oriented — what it is*

- [Chief-powered construction — the batch, driven unattended and for free](reference/chief-powered-construction.md)
- [Curriculum — the generated index of every seed notebook and its badge](reference/curriculum.md)
- [The gate's authority — which process holds the answer key](reference/gate-authority.md)
- [JupyterLite — the tutorial runtime in the browser](reference/jupyterlite.md)
- [Packaging Praxis](reference/packaging.md)
- [Storage — where your work is kept](reference/storage.md)

## Explanation

*understanding-oriented — why it is this way*

- [Dead-code inventory — the measured candidate list for the hygiene sweep](explanation/dead-code-inventory.md)
- [Documentation sweep — what was archived, what was left alone, what was not verified](explanation/documentation-sweep.md)
- [Seed Domain Addition Policy](explanation/domain-addition-policy.md)
- [Gap Analysis](explanation/gap-analysis.md)
- [What a gated domain costs — the first measured backfill](explanation/gating-backfill-cost.md)
- [jupyterquiz — assessed, declined](explanation/jupyterquiz-assessment.md)
- [Notebook Completion Rubric](explanation/notebook-rubric.md)
- [Seed refresh policy](explanation/seed-refresh-policy.md)

## Archive

*not current — kept because deleting a document destroys the reasoning behind it*

Archived documents are deliberately **not** listed above as current, and are exempt from
the index rule for that reason; they are linked here so a reader can find the reasoning
rather than only its absence. Each one's banner names what replaced it, when, and what
was replaced by nothing.

- [Technologies — the original study list](archive/technologies.md) · *archived
  2026-09-03; its catalog half superseded by the generated
  [curriculum](reference/curriculum.md) and [gap analysis](explanation/gap-analysis.md),
  its 145 unbuilt entries replaced by nothing*

## The shape of this tree

The standard's set of seven directories is a **ceiling, not a quota**: praxis has
`reference/`, `explanation/` and `archive/` and nothing else, because it has not yet
written a tutorial, a task guide, an ADR or a runbook. Checked 2026-09-03 — there is
**no directory under `docs/` outside the standard's seven**, so this repo declares no
exceptions and carries no `docs/.structure-exceptions` file.

Two of these are **generated** from `curriculum.py` by `generate_docs.py` (`make docs`)
and must not be edited by hand: [`reference/curriculum.md`](reference/curriculum.md) and
[`explanation/gap-analysis.md`](explanation/gap-analysis.md). The generator writes the
banner too, so regenerating them keeps them compliant rather than silently demoting them.

Both halves of this page are gated rather than remembered, in `.chief/verify.sh` **and** in
CI: `scripts/check-doc-links.mjs` holds every local reference to something that exists (a
ratchet — rot cannot grow), and `scripts/check-docs-structure.mjs` holds the three rules
above — index coverage, banners, and the closed directory set.

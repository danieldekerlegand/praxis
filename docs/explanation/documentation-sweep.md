# Documentation sweep — 2026-09-03

> **Status:** Current · **Updated:** 2026-09-03 · **Owner:** praxis

The record of the `chief/901-docs-tell-the-truth` sweep: what was archived, what was
deliberately left alone, and — the part a sweep usually omits — **what it did not verify**.
It is the docs half of what `dead-code-inventory.md` is for code, and it exists for the same
reason: a sweep that leaves no account of its method is a sweep nobody can review or re-run.

It also closes a handoff. `dead-code-inventory.md`'s Class E left `technologies.md`
undecided — "a **document**, not code … the docs sweep's call, not this one's". This is that
call, made below.

## What was archived

**One document.** `technologies.md` → [`docs/archive/technologies.md`](../archive/technologies.md),
banner `Archived`, with a note naming what replaced it, when, and what was replaced by nothing.

It is the **original study list** — the hand-written catalog praxis was built from, and the
only record of what the library was asked to cover before `curriculum.py` existed. Two things
made archiving it the right call rather than either keeping it or deleting it:

1. **Its live half already has a generated successor that cannot drift.**
   `docs/reference/curriculum.md` and `docs/explanation/gap-analysis.md` are written by
   `generate_docs.py` from `curriculum.py` plus the on-disk badges.
2. **By hand, it had already drifted, and that is measurable.** All 133 of its notebook links
   resolve — but **6 of its 145 `_notebook not yet written_` entries are wrong**: the notebook
   exists (OWL, Finetune Tranformer LM, Model Context Protocol, Agent-to-Agent, Agent
   Development Kit, ReAct). A hand-maintained catalog beside a generated one is the same
   defect as two implementations of one behaviour.

It is `Archived`, **not** `Superseded`, and the distinction is load-bearing: its 145 unbuilt
entries were replaced by *nothing*. No live document tracks them and `curriculum.py`'s
manifest does not contain them. The banner says so, because an archived document quietly
holding the only copy of a backlog is how a backlog is lost.

Its 133 links were **repointed, not retargeted** — `notebooks/` → `../../notebooks/`, a
consequence of the file moving, not of the tree moving. Every link points at the same file it
pointed at before, verified by reconstructing the pre-move text and comparing: the body is
byte-identical. `scripts/check-doc-links.mjs` exempts `docs/archive/` from being a *citer*
precisely so an archived doc is not edited to describe today's tree; that exemption is about
retargeting, and repairing a path broken by the move is the opposite of it.

**Nothing was deleted.** No document was removed by any story in this tasklist.

## What was left alone, and why

A document that looks stale but records a decision is not stale — it is history, and this
portfolio keeps those on purpose.

| Left alone | Why |
| --- | --- |
| `explanation/dead-code-inventory.md` | The record of the `900` sweep, written before anything was removed. Its Class E row still reads "the docs sweep's call, not this one's" — accurate as of the day it was written, and rewriting it would falsify the work record. This page answers it instead. |
| `explanation/jupyterquiz-assessment.md` | A decision record. US-2 **re-measured** the proportions the DECLINE rests on (50/34/16 % against the 50/33/17 % argued from, `python3 -m praxis.gateaudit`) and confirmed the conclusion stands, so the decision's own figures are left at the sizes it was taken on rather than restated at today's. A decision is evidence about a moment. |
| `explanation/gap-analysis.md`, `reference/curriculum.md` | Generated. Never hand-edited; `python3 generate_docs.py` produces a zero-byte diff. |
| `explanation/domain-addition-policy.md`, `explanation/seed-refresh-policy.md` | Policies, still current: `praxis.promote` and `praxis.refresh` exist and behave as described. |
| The `notebooks/` prose and `tasks/chief/completed/` | Product assets and the work record. Both are deliberately out of every gate's citer set for the same reason. |

**Out of scope by the tasklist, so reported rather than fixed.** `ROADMAP.md` says "the three
storage backends" and is wrong exactly the way `README.md` was before US-2 corrected it — four
ship, `webdav` being the fourth through `register_backend()`. The tasklist puts roadmaps out of
scope (they were reconciled portfolio-wide on 2026-09-02/03 under their own evidence standard),
so it is recorded here instead of silently changed.

## What this sweep did NOT verify

The honest limit, stated because the claim "the docs are now true" is stronger than the method
supports.

- **Prose correctness is not machine-checkable and was not machine-checked.** What was verified
  is every claim that could be executed or grepped: each backticked path resolved, each
  `symbol()` cited in prose grepped for a definition, each route in README's API table matched
  against `launcher/app.py`'s decorators, and each count re-measured by running the command that
  produces it. That the *remaining* prose is true is not established by any of it — only that
  its checkable parts are.
- **The two gates check shape, not truth.** `check-doc-links.mjs` proves a reference resolves,
  never that the target says what the citer implies. `check-docs-structure.mjs` proves a banner
  exists and parses, never that its `Updated` date or `Status` is honest — a banner is an
  assertion by its author, and the gate can only insist that the assertion is present.
- **External URLs are unchecked, by design.** The link gate is local-only: a checker that fails
  for network reasons is a checker that gets disabled. The seed notebooks' Resources links are
  held by `rubric.construction_failures` at write time, not here.
- **The archived document was not re-verified as a catalog.** Its 6 measured errors are the
  evidence for archiving it; there was no attempt to find the rest, because a document declared
  not-current does not earn that work.
- **One gate was repaired mid-sweep, which means it had been passing vacuously.**
  `check-docs-structure.mjs`'s "Superseded/Archived must say what replaced it" clause stripped
  `BANNER` from a joined multi-line string, but `BANNER` is `^…$`-anchored with no `m` flag, so
  it never matched, the banner's own text always remained, and the emptiness test could not
  fail. It was corrected to read the three lines *following* the banner and re-proved to fire.
  US-1 reported that guard as proved-firing and it was — on R1 and R3, the rules it was probed
  with. **A gate is proved only on the rules you actually inject a violation for.**

## The gates this sweep added

Both are wired into `.chief/verify.sh` **and** `.github/workflows/ci.yml`, on the same
`\.md$|^docs/` predicate; CI carried neither before.

- `scripts/check-doc-links.mjs` — every local reference resolves. A **ratchet** against the PR
  base, so rot cannot grow and pre-existing rot is retired deliberately.
- `scripts/check-docs-structure.mjs` — R1 index coverage · R2 banners · R3 the closed directory
  set · R4 the Tier-1 root. A **wall**, because the tree was brought fully compliant here and
  there is nothing to grandfather. R4 was added by US-3 rather than US-1 on purpose: it would
  have been red on the day it landed, and a gate that is red on arrival is a gate someone
  switches off.

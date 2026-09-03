# jupyterquiz — assessed, declined

> **Status:** Current · **Updated:** 2026-09-03 · **Owner:** praxis
> **Decision: DECLINE.** Measured 2026-08-22. Revisit only on the trigger at the end.

The 2026-08-13 portfolio scan proposed jupyterquiz as a socket rather than a
competitor: praxis hand-builds its knowledge-check surface, and
[jupyterquiz](https://github.com/jmshea/jupyterquiz) is "an interactive Quiz generator
for Jupyter notebooks and Jupyter Book". The split offered for test was that
jupyterquiz would carry **question rendering and answer capture**, while praxis keeps
the rubric, the anti-fabrication audit, and the reference-`solution`-run-against-its-own-`test`
subprocess verification.

This is the record of that assessment. The same scan validated praxis's two other
adoption calls — nbgrader (`chief/84`) and JupyterLite (`chief/85`) — so the answer here
is not a reflex against dependencies. It is a specific no.

## The boundary that may not move

Stated first, because it is what the assessment measures against. Adopting a rendering
surface may **not** move any of:

- **The grader.** `checks.checkset_failures()` is the write gate. A set that fails it is
  never written — the same rule the constructor follows for notebooks.
- **The rubric.** `GATED_SECTIONS`, derived from `rubric.RUBRIC_SECTIONS`, decides which
  sections carry a gate. A section list that comes from a widget's capabilities instead is
  the tail wagging the dog.
- **The subprocess verification.** A `code` check's reference `solution` is run against its
  own `test` in a subprocess before the set may be written. This is the load-bearing check
  and no quiz widget performs it — it is what makes "auto-graded" mean something.
- **The server-side gate.** `checks.learner_check()` is the only way a check reaches a
  client: `answer`, `solution`, `test` and `expected` never cross it, a locked section
  serves no checks at all, and `POST /api/study/<rel>` answers **423** for a section the
  learner has not reached. A disabled button is not the gate.

The first three survive any rendering swap. The fourth is where jupyterquiz fails.

## Maintenance base

Recorded 2026-08-22 from the GitHub API and PyPI:

| | |
|---|---|
| Repository | `jmshea/jupyterquiz`, created 2021-06-15 |
| Stars / forks | 166 / 48 |
| Open issues | 5 |
| Last push | 2026-03-05 (~5.5 months before measurement) |
| Latest release | 2.9.6.4 |
| Licence | MIT |
| Maintainer | John M. Shea — a single author |

Not abandoned, and not archived. But a bus factor of one on a package that would sit on
the learner-facing path. For comparison, the two adoptions praxis *did* take are
nbgrader (a Jupyter-org project) and JupyterLite (4,868 stars, BSD-3-Clause, pushed
2026-08-10). The standing rule is to adopt nothing with poor support; jupyterquiz is
borderline on that rule alone. It is not, however, the reason for the decline.

## What it would actually carry

Measured against the seed library on 2026-08-22: **24 checksets, 144 checks — 72 `choice`,
48 `short`, 24 `code`.**

> **[CORRECTED 2026-09-03 — "as it ships" was true on 2026-08-22 and is not now: `chief/87`
> ran the gating backfill and the library carries 117 checksets, 702 checks — 354
> `choice`, 236 `short`, 112 `code` (`python3 -m praxis.gateaudit`). Re-measured rather
> than assumed, because the decline below rests on the *proportions*, not the totals: they
> are 50% / 34% / 16%, against the 50% / 33% / 17% argued from here. The paragraph's
> conclusion is unchanged and the figures below are left at the sizes the decision was
> actually taken on, which is what a record of a decision is for.]**

- `choice` (72, 50%) maps cleanly onto jupyterquiz's `multiple_choice` / `many_choice`.
- `short` (48, 33%) maps only loosely. jupyterquiz's `string` type is an exact or
  fuzzy-threshold string match against an enumerated answer list. Praxis grades a `short`
  answer with the model against `expected`, and records the learner's answer verbatim on
  the `CheckOutcome`. Reducing that to fuzzy string matching is a downgrade in what the
  gate can ask, not a rendering change.
- `code` (24, 17%) has **no analogue**. jupyterquiz has no learner-written-code type and
  no execution. These are exactly the checks the subprocess verification exists for.

So the widget covers half the library outright, a third with a loss of grading power, and
none of the sixth that carries the anti-fabrication weight.

## Why the decline

**1. Its rendering is inseparable from its grading, and its grading is client-side.**
jupyterquiz's render input *is* the answer key: a question is an `answers` array whose
entries carry `correct` and `feedback`. Grading happens in the browser against that array.
To use it "only as a renderer" you must hand it the key — which is precisely what
`learner_check()` exists to prevent. The README's own answer to this is obfuscation, not a
boundary: *"You can now embed the question source (most importantly, the answers) in
Jupyter Notebook so that they will not be directly visibile to users"* — base64 in the page
is still in the page.

This is the same tension `chief/85` settled for JupyterLite, and settled the other way:
JupyterLite is the **runtime** for notebook content while gate authority stays in a process
the learner does not control. jupyterquiz cannot take that shape, because for jupyterquiz
the gate *is* the browser.

**2. Answer capture does not reach a server at all.** Response preservation
(`preserve_responses=True`) emits text the student must copy and paste into a Markdown
cell — the README attributes this to "limitations in the exchange of information from the
JavaScript side to the Python side". Praxis persists the whole `CheckOutcome`, learner's
answer included, as one JSON file per learner under `progress_dir()`, and re-derives every
unlock from those outcomes on each request. Copy-paste is not a substitute for the half of
the split jupyterquiz was proposed to carry.

**3. It would be a third rendering that agrees with neither existing one.** Since `chief/84`
a check is an nbgrader-schema graded cell in the notebook, and `ui/src/KnowledgeChecks.tsx`
(190 lines, holding no unlock logic) renders whatever the launcher says. jupyterquiz's JSON
is a fourth schema to keep in step with those, for a surface that already works.

**4. Its known breakages sit on praxis's roadmap.** The README documents LaTeX rendering
broken under JupyterLab 4 and `id` tags stripped by Jupyter 4.2.5+, each with a
hand-applied workaround. `chief/85` puts a JupyterLab 4 in every learner's browser.

**A small dependency for a surface praxis already has working is a legitimate no.** That is
this one.

## What would reopen it

A version of jupyterquiz that accepts a *keyless* question payload and posts the learner's
response to a caller-supplied endpoint for grading. That is the shape the split needed, and
it would leave all four boundary items above untouched. Absent that, praxis keeps its own
surface and spends the effort on the grader instead — which is what the rest of this band
does.

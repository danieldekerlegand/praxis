# Praxis — Roadmap

> Constructs **interactive, gated notebook tutorials** for any user-defined subject: you name
> a subject, AI agents build the tutorials to a rubric, and AI-built knowledge checks gate a
> learner's progression through them. North star: *demonstrated understanding, not scrolling —
> a self-hostable tutorial constructor for any topic.*

**Status:** Feature-complete (the 10→60 Chief program has shipped) — in polish + growth mode · **Last updated:** 2026-08-11

This is the single canonical roadmap. Praxis had no prior ROADMAP; this consolidates the
README, `CLAUDE.md`, the reference docs under [`docs/`](docs/), and the completed 6-tasklist
Chief program into one reality-checked picture. The `docs/` files are reference contracts, kept
in place and linked below; there was no separate roadmap document to relocate.

---

## Vision & Scope

Praxis turns *"I want to learn X"* into a gated, interactive tutorial without an author writing
it by hand:

1. **You define any subject** — free text in, an AI-generated curriculum out (modules → topics,
   one notebook per topic).
2. **AI agents construct each tutorial to a rubric** — the 8-section
   [notebook rubric](docs/notebook-rubric.md) is the definition of "complete"; a constructed
   notebook is graded against it and only written when it passes.
3. **Knowledge checks gate progression** — each section carries AI-built checks; a later section
   unlocks only when every check in every earlier section has a passing outcome. The unlock is
   *derived* from recorded outcomes, never stored, and a locked section hands the client nothing
   — not the answer key, not even the question.

It grew out of `ai-tutor`, a static study-notebook library, whose machinery (rubric ·
scaffolder · construction loop · completion gate · launcher) and **245 seed notebooks across
14 domains** are reused as the foundation and as worked examples of a finished tutorial.

**Product shape:** a **standalone** Tauri desktop/web app over a Python construction core. The
Python core (`praxis/`, `curriculum.py`, `launcher/`, `scaffold_notebooks.py`) is the product;
`src-tauri/` + `ui/` are a shell around it.

**Ecosystem posture:** BYO-key LLM access with an **optional** `AGORA_BASE_URL` to route through
agora's provider-router — no hard fabric dependency. It joins the ecosystem when pointed at it,
runs fully on its own otherwise.

**In scope:** subject definition, agentic construction, the gate, the three storage backends,
desktop/web packaging, the seed library.
**Out of scope:** being a general LLM gateway (defer to agora), hosting a shared knowledge graph
(that is pinakes), model training (that is lugh).

## Current State

- **Rebranded and shelled.** `ai-tutor` → **Praxis**; a Tauri desktop/web shell wraps the
  preserved Python core, and the seed library browses inside it.
- **Subject → curriculum → scaffold → construct → gate** is the working end-to-end loop:
  `praxis/curriculum_gen.py` (define), `scaffold_notebooks.py` (scaffold), `praxis/construct.py`
  (construct, graded by `praxis/rubric.py`), `praxis/checks.py` (build checks),
  `praxis/progress.py` (derive unlocks).
- **BYO-key LLM client** with optional agora routing; browsing/rendering/answering need no key —
  only the two model-backed writes (define, construct) and grading a `short` answer do.
- **Three storage backends** — `app` (default, per-OS app dir), `drive` (a picked folder,
  verbatim), `cloud` (a local mirror + S3-compatible sync, no boto3) — all writing one root
  layout, selectable in-app. See [`docs/storage.md`](docs/storage.md).
- **Packaged & CI-gated** — `tauri build` desktop bundles (verified `Praxis_0.1.0_aarch64.dmg`)
  plus an optional web build; CI runs the frontend build, the Rust build, and `pytest tests/`
  path-scoped on every PR. See [`docs/packaging.md`](docs/packaging.md).
- **Gating is the differentiator and it is largely unshipped: 24 of 245 seed notebooks are gated.**
  The machinery is real and proven; the coverage is not. The backfill (`chief/79`–`81`, retargeted
  onto the nbgrader schema) is what makes the claim true, and it is prioritized breadth-first.
- **Chief program:** 6/6 built-program tasklists (`10`–`60`) merged; **16 proposed forward tasklists authored** (`tasks/chief/*.json`, `passes:false`, unrun) — pending a run, not merged.

---

## Milestones

One list, everything: shipped and planned. The `10`→`60` block is the executed Chief program
(mapped to its bands); **Planned / product hardening** is the modest, mined-but-unbuilt next
work; **Loose wishlist** is steady-state and smaller open threads. This is a **standalone
product** — the planned work is polish and depth, deliberately not a large program. Status
legend: **✅ shipped/merged · 🚧 partial / in-progress · ⬜ planned**. The Tasklist column is the
Chief tasklist that delivered a row (✅ merged) or the *(proposed)* one that would (bands `70`+;
`10`–`60` are used).

### The 10→60 build program — ✅ shipped

The 6-tasklist Chief program maps one-to-one onto the product milestones. Bands 20, 30, 40 are
the generation/learning spine; 50 ran in parallel off the shell. Dependency spine:
`10 → 20 → 30 → 40 → 60`, with `50` branching off `10` and rejoining at `60`.

| Status | Milestone | Tasklist |
|---|---|---|
| ✅ | **Foundation** — rebrand `ai-tutor` → Praxis (preserving the reusable core) + a building Tauri desktop/web shell that browses the existing library | `10-rebrand-and-tauri-shell` |
| ✅ | **Define** — any user-defined subject → AI-generated curriculum → rubric-shaped scaffolded notebooks; the shared BYO-key LLM client (agora optional) | `20-user-defined-subjects` |
| ✅ | **Construct** — AI agents fill each scaffold to the rubric (the headline "AI builds the tutorial"); in-app flow with live status, batched across a curriculum | `30-agentic-construction` |
| ✅ | **Gate** — AI-generated per-section knowledge checks + gated progression (derived unlocks, locked sections serve nothing) | `40-gated-progression` |
| ✅ | **Storage** — subjects, tutorials, and progress across three interchangeable backends (app / drive / cloud), selectable in-app | `50-storage-integrations` |
| ✅ | **Ship** — Tauri desktop bundles + optional web build, CI gate on every PR, end-user docs carrying a clean first-run through the whole loop | `60-package-and-distribute` |

### Planned / product hardening — ⬜ planned

The 10→60 program is complete; what remains is polish and optional depth for the standalone
product — none of it blocking, none of it a new program. All rows below are now authored
(`tasks/chief/*.json`, `passes:false`, unrun).

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **Signed / notarized release builds** — bundles ship unsigned today (macOS Gatekeeper needs a right-click → Open; [`docs/packaging.md`](docs/packaging.md)); wire a signing identity + notarization when a distribution channel is chosen, keeping `version` in step across `tauri.conf.json` / `pyproject.toml` / `ui/package.json` · S/M | `chief/70-signed-notarized-builds` *(proposed)* |
| ⬜ | **Embed the Python interpreter** — a shipped `.app` currently needs the checkout + launch-extra venv beside it (the shell discovers the core at runtime; nothing is embedded, `src-tauri/src/library.rs`); embedding an interpreter makes a truly standalone bundle · M | `chief/71-embed-python-interpreter` *(proposed)* |
| ⬜ | **Deeper opt-in agora integration** — richer provider-router use behind `AGORA_BASE_URL`, beyond the BYO-key + optional routing that ships, without ever becoming a hard dependency · S/M | `chief/72-deeper-agora-integration` *(proposed)* |
| ⬜ | **Additional storage backends** — the resolver design (`_RESOLVERS` + `_AVAILABLE` in `praxis/storage.py`) makes a new backend a resolver + availability check with no change to any caller; add on demand · S | `chief/73-additional-storage-backends` *(proposed)* |
| ⬜ | **Seed-library refresh** — steady-state ownership of the 245-seed corpus: a rot audit (URL liveness + `compile()` re-check, report-only), a refresh policy (flagged-for-human by default; force-regenerate only explicitly, through the shipped grader — a ✅ seed is never silently rewritten), a promotion path for the [`docs/gap-analysis.md`](docs/gap-analysis.md) §2 additions, and a domain-addition policy (numbering appends 16+; the `06` hole is never reused) · M | `chief/83-seed-library-refresh` *(proposed)* |

### Loose wishlist — ⬜ / 🚧 ongoing

Steady-state upkeep and smaller open threads, not big enough to anchor a tasklist.

| Status | Milestone | Tasklist |
|---|---|---|
| 🚧 | **Seed-library upkeep** — the 245 seed notebooks (14 domains) and their coverage stay current as tooling evolves; the recommended additions in [`docs/gap-analysis.md`](docs/gap-analysis.md) (§2, across every domain) are a running backlog. Now owned: the rot audit, refresh policy, §2 promotion path and domain-addition policy are `chief/83` | `chief/83-seed-library-refresh` *(proposed)* |
| 🚧 | **Rubric / anti-fabrication tightening** — `construction_failures` and `checkset_failures` grow each time a new model fabrication is found; keep the grader's sentences specific (they are also the UI's error text) | — |

### JD-driven tutorial suggestion — ⬜ proposed

A net-new growth surface, **not present in the code today**: import a job description, extract
what the job actually demands, and suggest tutorials that close the learner's gap — routed into
the *existing* define → scaffold → construct → gate pipeline rather than a parallel one. The hard
part is not generation but **restraint**: the 245-notebook library (14 domains) plus the
`recommended`-tagged neighbours already scaffolded in `curriculum.py` and catalogued in
[`docs/gap-analysis.md`](docs/gap-analysis.md) must be held in mind so a suggestion is a genuine
gap, never a redundant re-tutorial of a topic that already ships. The accepted suggestions become
subjects the shipped `curriculum_gen.py` / `scaffold_notebooks.py` build exactly as a hand-typed
subject would — this phase adds the front of the funnel, not a second constructor.

*Depends on:* the shipped **Define** (`20`) + **Construct** (`30`) spine (suggestions feed the
existing scaffolder); [`docs/gap-analysis.md`](docs/gap-analysis.md) + `curriculum.py`'s
`recommended` tags as the dedup corpus.

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **JD ingest** — import a job description by **copy-paste or file upload** (parse `.txt`/`.md`/`.pdf`/`.docx` to plain text), normalize to one canonical JD document; a BYO-key-optional read path (plain text needs no model) | `chief/74-jd-ingest` *(proposed)* |
| ⬜ | **Requirement & skill extraction** — model-backed pass turning a JD into a structured list of required skills / tools / competencies, normalized leniently and graded strictly in the `curriculum_gen.py` house style (ask JSON, normalize, validate before use) | `chief/75-jd-requirement-extraction` *(proposed)* |
| ⬜ | **Gap analysis vs the library** — match extracted requirements against the existing 245 notebooks (14 domains) + the `recommended` neighbours, classifying each requirement as *covered* / *partially covered* / *missing*, reusing the `docs/gap-analysis.md` coverage model | `chief/76-jd-library-gap-analysis` *(proposed)* |
| ⬜ | **Suggestion + dedup engine** — turn *missing* / *partial* requirements into proposed subjects, deduplicated against existing topics and domains so no suggestion re-tutorials shipped material; each suggestion carries its source requirement and its gap rationale | `chief/77-jd-suggestion-dedup-engine` *(proposed)* |
| ⬜ | **Review / accept surface** — an in-app view to review, edit, drop, or accept suggestions; an accepted one becomes a subject handed to the shipped `POST /api/subjects` → scaffold → construct flow (no new constructor, just a new entry point) | `chief/78-jd-suggestion-review-surface` *(proposed)* |

### Adopt the Jupyter grading ecosystem — ⬜ proposed, **runs before the gating backfill**

Added 2026-08-11 by **decision D10** in `rosetta/strategy/DECISIONS.md` (private).
Two adoptions, both permissively licensed and both replacing something praxis invented in parallel.

**[nbgrader](https://github.com/jupyter/nbgrader)** (1,369★, BSD-3-Clause, pushed 2026-07-31) already
ships the mature **hidden-test abstraction** — `### BEGIN HIDDEN TESTS` / `### END HIDDEN TESTS` and
solution-region stripping — that `tests/test_notebooks.py` and `praxis/checks.py` reimplement, plus a
**cell-level metadata schema for graded regions** (`metadata.nbgrader`) that is a de-facto standard.
Praxis's `metadata.praxis` + `<slug>.checks.json` sidecar is a parallel invention of the same thing.
Adopting the schema buys interop with the whole Jupyter grading ecosystem, and **`nbgrader validate`
becomes the authoritative gate** in place of bespoke pytest.

**What praxis keeps is the genuinely novel half: construction** — subject → curriculum →
rubric-shaped scaffold → AI-filled tutorial → auto-authored checks. nbgrader has **zero content
generation** and no OSS competitor exists for that pipeline. Praxis becomes an nbgrader-schema
*producer*. Two honest gaps are carried explicitly rather than hidden: nbgrader is code-centric and
has no equivalent of praxis's `choice`/`short` checks (kept as a namespaced, documented extension),
and the server-side boundary — `learner_check()`, a locked section serving *nothing*, `423` on an
unreached section — must survive a format whose release artifact keeps everything in one file.

**[JupyterLite](https://github.com/jupyterlite/jupyterlite)** (4,868★, BSD-3, pushed 2026-08-10)
deletes praxis's single worst friction. The README today requires a Python install, the launch extra,
a kernel registration, and **`praxis-lab` + `praxis-launch` in two terminals** before a learner sees a
tutorial. A Tauri app bundling JupyterLite needs **no local Python at all** for the learner path.
The architectural tension is stated in the tasklist and must be settled there, not ducked: JupyterLite
has no server, so the gate's authority stays in the Tauri backend (or `chief/71`'s embedded
interpreter) and only what `learner_check()` permits crosses into the browser. Construction still
needs the Python core and a key, and the docs draw that line.

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **nbgrader cell schema + hidden-test mechanics** — emit `metadata.nbgrader` graded cells with stable `grade_id`s, adopt nbgrader's solution/hidden-test delimiters and release mechanics (deleting the reimplementation), carry `choice`/`short` as a namespaced extension, and make `nbgrader validate` the authoritative gate; the 24 already-gated seeds migrate by an idempotent pass · M/L | `chief/84-nbgrader-cell-schema-adoption` *(proposed)* |
| ⬜ | **JupyterLite delivery** — bundle a pinned JupyterLite site in the Tauri app so a learner reaches a running tutorial with zero terminals, zero `pip install` and zero kernel registration; serve only *released* (stripped) notebooks; keep the gate's authority out of the browser; report honestly when a tutorial's deps are not Pyodide-resolvable · M/L | `chief/85-jupyterlite-delivery` *(proposed)* |

### Gating backfill program — ⬜ proposed

> **Flag the reality first: only 24 of the 245 seed notebooks are gated today.** Gating is praxis's
> headline differentiator and it is **largely unshipped** until this backfill lands — 221 notebooks
> are browsable-but-ungated (a topic with no checks gates nothing, by design — `praxis/progress.py`).
> That is why the backfill is prioritized **breadth-first and shallow**: a real, modest gate on every
> one of the 14 domains moves the product further than an exhaustive gate on three, and the
> per-domain fraction — not the overall one — is the number `chief/80` puts in front.

This program drives the remaining ~221 to gated by **reusing the shipped check machinery unchanged**
— `praxis/checks.py` over `GATED_SECTIONS`, and the derived-unlock gate in `progress.py` — run in
per-domain batches rather than one sweep, with the anti-fabrication verification (the reference
`solution` run against its own `test` in a subprocess) held as the quality bar it already enforces.

**Retargeted 2026-08-11 by D10:** the format this band writes at scale is now the **nbgrader schema**
adopted in `chief/84`, not the parallel `<slug>.checks.json` sidecar it was originally written
against — backfilling 221 notebooks into a format about to be retired would be the most expensive
possible way to discover the adoption. All three rows therefore gain a hard dependency on `84`.

*Depends on:* `chief/84` (the schema and the `nbgrader validate` gate) plus the shipped **Gate**
(`40`) machinery — this phase runs it at scale, it invents no new gating primitive.

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **Batched gating program (by domain)** — drive the ~221 ungated notebooks to gated in **breadth-first** per-domain batches across the 14 domains, writing `84`'s nbgrader schema, with no rewrite of an already-✅ notebook (same idempotence as construction) · depends on `84` | `chief/79-gating-backfill-by-domain` *(proposed)* |
| ⬜ | **Coverage tracker (X/245 gated)** — a report of gated coverage overall and **per domain as the primary figure** (start line: **24/245**), surfaced in-app off the same `_gated()` view-model data, so a batch's progress is visible and resumable · depends on `84` | `chief/80-gating-coverage-tracker` *(proposed)* |
| ⬜ | **Gate-quality / anti-fabrication pass** — audit generated gates for fabricated or trivial questions and tighten the write-path grader so backfilled gates hold the same bar as hand-built ones, owning **exactly the residue `nbgrader validate` cannot judge** (triviality, an answer given away, a test that asserts nothing) rather than re-implementing it · depends on `79` + `84` | `chief/81-gate-quality-anti-fabrication` *(proposed)* |

### Chief-powered tutorial construction — ⬜ proposed

A lighter integration that lets the two phases above run **at scale and cheaply**: notebook
construction and gating are driven as Chief tasklists on OpenCode + self-hosted / local inference,
rather than one interactive in-app run per notebook. Praxis already has the batch loop
(`construct_each` / `construct_domain` / `construct_subject`) and the resumable, idempotent
skip-if-✅ contract that makes an unattended run safe; this wires that loop to Chief's headless
driver so a whole domain's gating backfill, or a JD-suggested subject, is one tasklist.

*Depends on:* **chief's proposed "Embeddable engine" capability** — headless invocation,
local-inference presets, roadmap→tasklist generation, and a status stream — referenced here as a
cross-repo dependency (`chief:80-headless-programmatic-invocation`, bands `80`–`84`, *now authored in chief*); and the
**Gating backfill** + **JD-driven** phases it accelerates.

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **Chief-driven construction + gating** — run `construct_each` / `checks.py` batches as Chief tasklists on OpenCode + local inference (headless, resumable via the existing skip-if-✅ contract), so gating backfill and JD-suggested subjects build unattended and cheaply · depends on `chief:embeddable-engine` | `chief/82-chief-powered-construction` *(proposed)* |

---

## Chief Tasklist Status

- **6/6 built-program tasklists merged** (`10`–`60`); **16 proposed forward tasklists authored** (`tasks/chief/*.json`, `passes:false`, unrun) — pending a run, not merged. Records in
  [`tasks/chief/completed/`](tasks/chief/completed/), each carrying its `mergedToMain` commit:
  `10-rebrand-and-tauri-shell` → `ef8c81d` · `20-user-defined-subjects` → `b6cce13` ·
  `30-agentic-construction` → `a7c23cb` · `40-gated-progression` → `509601f` ·
  `50-storage-integrations` → `707cc24` · `60-package-and-distribute` → `6ca7bef`.
- **16 proposed tasklists** (`chief/70`–`chief/85`) back the **Planned / product-hardening**, JD-suggestion, **Jupyter-ecosystem adoption**, gating-backfill, Chief-construction, and seed-library-refresh phases
  above — **all now authored** (`tasks/chief/70`–`85`, `passes:false`, unrun); of the loose
  wishlist rows, seed-library upkeep is now owned by `chief/83` and only the
  rubric-tightening thread carries no tasklist (its next concrete step is `chief/81`).
- **Scheduling note:** task numbers are stable identifiers, not execution order — `dependsOn` is
  authoritative. `chief/84` (nbgrader schema) must run **before** `chief/79`–`81` despite its higher
  number, because those three now write the schema it adopts; `chief/85` (JupyterLite) depends on
  `84` because it is `84`'s *released* notebooks that are safe to hand to an untrusted browser.
- The 6-tasklist built program is complete; the 16 proposed forward tasklists above are authored
  but unrun (open work once scheduled). (Earlier offline notebook-filling runs used
  Ralph/ralphy — `ralph/`, `.ralphy/` — and are historical, superseded by the in-app
  construction agent from band 30.)

---

## Related Docs

Reference contracts (living docs, kept in place):
- [`docs/notebook-rubric.md`](docs/notebook-rubric.md) — the definition of a complete tutorial
  (8 sections, runnable vs conceptual) and the knowledge-check rules; the shape of the gate.
- [`docs/storage.md`](docs/storage.md) — the one-root layout and the app / drive / cloud backends.
- [`docs/packaging.md`](docs/packaging.md) — desktop bundle + optional web build + CI contract.
- [`docs/gap-analysis.md`](docs/gap-analysis.md) — seed-library topic coverage and recommended additions.

Project orientation:
- [`README.md`](README.md) — install, the reusable core, and first-run.
- [`CLAUDE.md`](CLAUDE.md) — the authoritative build/test/quality gates and the module-by-module
  design of the construct → check → gate → storage pipeline.

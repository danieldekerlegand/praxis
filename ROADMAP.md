# Praxis — Roadmap

> Constructs **interactive, gated notebook tutorials** for any user-defined subject: you name
> a subject, AI agents build the tutorials to a rubric, and AI-built knowledge checks gate a
> learner's progression through them. North star: *demonstrated understanding, not scrolling —
> a self-hostable tutorial constructor for any topic.*

**Status:** Feature-complete (the 10→60 Chief program has shipped) — in polish + growth mode · **Last updated:** 2026-08-10

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
- **Chief program:** all 6 tasklists (`10`–`60`) merged; **nothing pending**.

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
product — none of it blocking, none of it a new program. Proposals only (no `tasks/chief/*.json`
authored yet).

| Status | Milestone | Tasklist |
|---|---|---|
| ⬜ | **Signed / notarized release builds** — bundles ship unsigned today (macOS Gatekeeper needs a right-click → Open; [`docs/packaging.md`](docs/packaging.md)); wire a signing identity + notarization when a distribution channel is chosen, keeping `version` in step across `tauri.conf.json` / `pyproject.toml` / `ui/package.json` · S/M | `chief/70-signed-notarized-builds` *(proposed)* |
| ⬜ | **Embed the Python interpreter** — a shipped `.app` currently needs the checkout + launch-extra venv beside it (the shell discovers the core at runtime; nothing is embedded, `src-tauri/src/library.rs`); embedding an interpreter makes a truly standalone bundle · M | `chief/71-embed-python-interpreter` *(proposed)* |
| ⬜ | **Deeper opt-in agora integration** — richer provider-router use behind `AGORA_BASE_URL`, beyond the BYO-key + optional routing that ships, without ever becoming a hard dependency · S/M | `chief/72-deeper-agora-integration` *(proposed)* |
| ⬜ | **Additional storage backends** — the resolver design (`_RESOLVERS` + `_AVAILABLE` in `praxis/storage.py`) makes a new backend a resolver + availability check with no change to any caller; add on demand · S | `chief/73-additional-storage-backends` *(proposed)* |

### Loose wishlist — ⬜ / 🚧 ongoing

Steady-state upkeep and smaller open threads, not big enough to anchor a tasklist.

| Status | Milestone | Tasklist |
|---|---|---|
| 🚧 | **Seed-library upkeep** — the 245 seed notebooks (14 domains) and their coverage stay current as tooling evolves; the recommended additions in [`docs/gap-analysis.md`](docs/gap-analysis.md) (§2, across every domain) are a running backlog, not a milestone | — |
| 🚧 | **Rubric / anti-fabrication tightening** — `construction_failures` and `checkset_failures` grow each time a new model fabrication is found; keep the grader's sentences specific (they are also the UI's error text) | — |

---

## Chief Tasklist Status

- **6/6 tasklists merged** (`10`–`60`); **0 pending**. Records in
  [`tasks/chief/completed/`](tasks/chief/completed/), each carrying its `mergedToMain` commit:
  `10-rebrand-and-tauri-shell` → `ef8c81d` · `20-user-defined-subjects` → `b6cce13` ·
  `30-agentic-construction` → `a7c23cb` · `40-gated-progression` → `509601f` ·
  `50-storage-integrations` → `707cc24` · `60-package-and-distribute` → `6ca7bef`.
- **4 proposed tasklists** (`chief/70`–`chief/73`) back the **Planned / product hardening** group
  above — **none authored yet** (no `tasks/chief/*.json`); they are roadmap stubs, and the loose
  wishlist rows carry no tasklist at all.
- No open autonomous work remains in this repo. (Earlier offline notebook-filling runs used
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

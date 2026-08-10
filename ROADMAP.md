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
scaffolder · construction loop · completion gate · launcher) and **221 seed notebooks** are
reused as the foundation and as worked examples of a finished tutorial.

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

The 6-tasklist Chief program (`10`→`60`) maps one-to-one onto the product milestones. Bands 20,
30, 40 are the generation/learning spine; 50 ran in parallel off the shell.

| Phase | Milestone | Chief tasklist | Status |
|---|---|---|---|
| 10 — Foundation | Rebrand `ai-tutor` → Praxis (preserving the reusable core) + a building Tauri desktop/web shell that browses the existing library | `chief/10-rebrand-and-tauri-shell` | ✅ merged `ef8c81d` |
| 20 — Define | Any user-defined subject → AI-generated curriculum → rubric-shaped scaffolded notebooks; the shared BYO-key LLM client (agora optional) | `chief/20-user-defined-subjects` | ✅ merged `b6cce13` |
| 30 — Construct | AI agents fill each scaffold to the rubric — the headline "AI builds the tutorial" capability; in-app flow with live status, batched across a curriculum | `chief/30-agentic-construction` | ✅ merged `a7c23cb` |
| 40 — Gate | AI-generated per-section knowledge checks + gated progression in the app (derived unlocks, locked sections serve nothing) | `chief/40-gated-progression` | ✅ merged `509601f` |
| 50 — Storage | Persist subjects, tutorials, and progress across three interchangeable backends (app / drive / cloud), selectable in-app | `chief/50-storage-integrations` | ✅ merged `707cc24` |
| 60 — Ship | Tauri desktop bundles + optional web build, CI gate on every PR, and end-user docs carrying a clean first-run through the whole loop | `chief/60-package-and-distribute` | ✅ merged `6ca7bef` |

Dependency spine: `10 → 20 → 30 → 40 → 60`, with `50` branching off `10` and rejoining at `60`.

---

## Remaining / Next

The 10→60 program is complete; what remains is polish, hardening, and optional depth — none of it
blocking.

**Ongoing (steady-state, not a phase):**
1. **Seed-library upkeep** 🚧 — the 221 seed notebooks and their gap-analysis coverage stay
   current as tooling evolves; recommended additions in [`docs/gap-analysis.md`](docs/gap-analysis.md)
   are a running backlog, not a milestone.
2. **Rubric / anti-fabrication tightening** 🚧 — `construction_failures` and `checkset_failures`
   are meant to grow each time a new model fabrication is found; keep the grader's sentences
   specific (they are also the UI's error text).

**One-off / candidate (not yet scheduled):**
3. **Signed release builds** ⬜ — bundles are currently unsigned (macOS Gatekeeper needs a
   right-click → Open); wire a signing identity + notarization when a distribution channel is
   chosen. Keep `version` in step across `tauri.conf.json` / `pyproject.toml` / `ui/package.json`.
4. **Bundle the Python core** ⬜ — today a shipped `.app` needs the checkout + launch-extra venv
   beside it (the shell discovers the core at runtime; no interpreter is embedded). Embedding an
   interpreter would make a truly standalone bundle.
5. **Deeper agora integration** ⬜ — optional, opt-in only: richer provider-router use behind
   `AGORA_BASE_URL` without ever becoming a hard dependency.
6. **Additional storage backends** ⬜ — the resolver design (`storage.register_backend`) makes a
   new backend a resolver + availability check with no change to any caller; add on demand.

---

## Chief Tasklist Status

- **6/6 tasklists merged** (`10`–`60`); **0 pending**. Records in
  [`tasks/chief/completed/`](tasks/chief/completed/), each carrying its `mergedToMain` commit.
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

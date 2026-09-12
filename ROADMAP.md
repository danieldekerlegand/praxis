# Praxis — Roadmap

> Constructs **interactive, gated notebook tutorials** for any user-defined subject: you name
> a subject, AI agents build the tutorials to a rubric, and AI-built knowledge checks gate a
> learner's progression through them. North star: *demonstrated understanding, not scrolling —
> a self-hostable tutorial constructor for any topic.*

**Status:** Feature-complete — the 10→60 Chief program and every forward tasklist (`70`–`87`, `900`, `901`) have merged and the gating backfill has **run**; the two stories the one overstating record (`86`) never landed are **built** in `chief/88` — in polish + growth mode · **Last updated:** 2026-09-12

> **Reconciled against the tree 2026-09-11.** `tasks/chief/completed/` holds **26** records — **26** merged (every `mergedToMain` sha an ancestor of `HEAD`), **0** retired. `tasks/chief/` holds **1** active — `88-finish-86-s3-client-and-llm-retry` (`fix`), which finishes `86`'s two unlanded stories. *(2026-08-25 read 23 of 23; `87`, `900` and `901` have merged since.)*
>
> The phase rows below were re-marked against those records on **2026-09-11** (they had last been
> revised 2026-08-11). A portfolio-wide audit on 2026-08-25 found every roadmap here **understating**
> what shipped and none overstating it; this pass found the first overstatement — **`86`'s record
> marks 3/3 stories passing, but its merge (`aa944fa`, 3 files, +26/−17) carries US-1 alone** (see
> the `chief/86` section below). Nothing gates this file — that absence is the measured cause, and
> the drift rate is about a fortnight. The finding stands as the record of that audit; the gap it
> named was **closed by `chief/88-finish-86-s3-client-and-llm-retry`** (`fd6efaf`, `684320d`), and
> the `chief/86` section carries the result.

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
   [notebook rubric](docs/explanation/notebook-rubric.md) is the definition of "complete"; a constructed
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

**In scope:** subject definition, agentic construction, the gate, the four storage backends,
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
- **Four storage backends** — `app` (default, per-OS app dir), `drive` (a picked folder,
  verbatim), `cloud` (a local mirror + S3-compatible sync over **minio-py**, no boto3 —
  `praxis/s3.py` is a 249-line adapter, see `chief/86` below) and `webdav` (a local mirror + WebDAV
  sync, added by
  `chief/73` through the public `register_backend()` seam) — all writing one root layout,
  selectable in-app. See [`docs/reference/storage.md`](docs/reference/storage.md).
- **Packaged & CI-gated** — `tauri build` desktop bundles (verified `Praxis_0.1.0_aarch64.dmg`)
  plus an optional web build; CI runs the frontend build, the Rust build, and `pytest tests/`
  path-scoped on every PR. See [`docs/reference/packaging.md`](docs/reference/packaging.md).
- **Gating is the differentiator, and the backfill has run: 117 of 245 seed notebooks are gated, in
  14 of 14 domains** (was 24/245 in 8 of 14). The machinery (`chief/79`–`81`) merged and then sat
  unrun for a fortnight; `chief/87` ran it, taking the six domains that had *no* gate at all to 100%.
  The remaining 128 are **deferred by a dated decision** on disk (`notebooks/ungated.json`), not
  forgotten — ungated with nothing on record is **0**. Coverage is now a ratchet the merge gate
  holds (`praxis/gatefloor.py` over `notebooks/coverage-floor.json`), and the README states it, so
  the number cannot go stale again without failing a build. Per-domain breakdown:
  `python3 -m praxis.coverage`; cost per notebook: `docs/explanation/gating-backfill-cost.md`.
- **Chief program:** 26 tasklists merged, `88` in flight — the built program (`10`–`60`, 6), the
  forward tasklists (`70`–`87`, 18) and the two closing sweeps (`900` dead code, `901` docs). One
  record overstated — `86` merged one of its three stories — and `chief/88` builds the other two
  (below). *(Rewritten 2026-09-11; this read
  "16 proposed forward tasklists authored … unrun", corrected-in-place 2026-08-25.)*

---

## Milestones

One list, everything: shipped and planned. The `10`→`60` block is the executed Chief program
(mapped to its bands); **Planned / product hardening** is the modest, mined-but-unbuilt next
work; **Loose wishlist** is steady-state and smaller open threads. This is a **standalone
product** — the planned work is polish and depth, deliberately not a large program. Status
legend: **✅ shipped/merged · 🚧 partial / in-progress · ⬜ planned**. The Tasklist column is the
Chief tasklist that delivered a row (✅ merged) or the *(proposed)* one that would (bands `70`+;
`10`–`60` are used). *(2026-09-11: every band-`70`+ tasklist has now run, so no row carries
*(proposed)* any more.)*

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

### Planned / product hardening — ✅ shipped

The 10→60 program is complete; this was the polish and optional depth for the standalone
product — none of it blocking, none of it a new program. **Every row below has merged** (shas in
[Chief Tasklist Status](#chief-tasklist-status)). *(Rewritten 2026-09-11; this read "all rows below
are now authored … unrun", corrected-in-place 2026-08-25.)*

| Status | Milestone | Tasklist |
|---|---|---|
| ✅ | **Signed / notarized release builds** — bundles ship unsigned today (macOS Gatekeeper needs a right-click → Open; [`docs/reference/packaging.md`](docs/reference/packaging.md)); wire a signing identity + notarization when a distribution channel is chosen, keeping `version` in step across `tauri.conf.json` / `pyproject.toml` / `ui/package.json` · S/M | `chief/70-signed-notarized-builds` |
| ✅ | **Embed the Python interpreter** — a shipped `.app` currently needs the checkout + launch-extra venv beside it (the shell discovers the core at runtime; nothing is embedded, `src-tauri/src/library.rs`); embedding an interpreter makes a truly standalone bundle · M | `chief/71-embed-python-interpreter` |
| ✅ | **Deeper opt-in agora integration** — richer provider-router use behind `AGORA_BASE_URL`, beyond the BYO-key + optional routing that ships, without ever becoming a hard dependency · S/M | `chief/72-deeper-agora-integration` |
| ✅ | **Additional storage backends** — the resolver design (`_RESOLVERS` + `_AVAILABLE` in `praxis/storage.py`) makes a new backend a resolver + availability check with no change to any caller; add on demand · S. **Shipped: `webdav`**, through the public `register_backend()` seam | `chief/73-additional-storage-backends` |
| ✅ | **Seed-library refresh** — steady-state ownership of the 245-seed corpus: a rot audit (URL liveness + `compile()` re-check, report-only), a refresh policy (flagged-for-human by default; force-regenerate only explicitly, through the shipped grader — a ✅ seed is never silently rewritten), a promotion path for the [`docs/explanation/gap-analysis.md`](docs/explanation/gap-analysis.md) §2 additions, and a domain-addition policy (numbering appends 16+; the `06` hole is never reused) · M | `chief/83-seed-library-refresh` |

### Loose wishlist — ⬜ / 🚧 ongoing

Steady-state upkeep and smaller open threads, not big enough to anchor a tasklist.

| Status | Milestone | Tasklist |
|---|---|---|
| 🚧 | **Seed-library upkeep** — the 245 seed notebooks (14 domains) and their coverage stay current as tooling evolves; the recommended additions in [`docs/explanation/gap-analysis.md`](docs/explanation/gap-analysis.md) (§2, across every domain) are a running backlog. Now owned: the rot audit, refresh policy, §2 promotion path and domain-addition policy merged in `chief/83` (`d22667d`); the upkeep itself stays open | `chief/83-seed-library-refresh` |
| 🚧 | **Rubric / anti-fabrication tightening** — `construction_failures` and `checkset_failures` grow each time a new model fabrication is found; keep the grader's sentences specific (they are also the UI's error text) | — |

### JD-driven tutorial suggestion — ✅ shipped

A net-new growth surface, **not present in the code when this was written** (it is now —
`chief/74`–`78` merged): import a job description, extract
what the job actually demands, and suggest tutorials that close the learner's gap — routed into
the *existing* define → scaffold → construct → gate pipeline rather than a parallel one. The hard
part is not generation but **restraint**: the 245-notebook library (14 domains) plus the
`recommended`-tagged neighbours already scaffolded in `curriculum.py` and catalogued in
[`docs/explanation/gap-analysis.md`](docs/explanation/gap-analysis.md) must be held in mind so a suggestion is a genuine
gap, never a redundant re-tutorial of a topic that already ships. The accepted suggestions become
subjects the shipped `curriculum_gen.py` / `scaffold_notebooks.py` build exactly as a hand-typed
subject would — this phase adds the front of the funnel, not a second constructor.

*Depends on:* the shipped **Define** (`20`) + **Construct** (`30`) spine (suggestions feed the
existing scaffolder); [`docs/explanation/gap-analysis.md`](docs/explanation/gap-analysis.md) + `curriculum.py`'s
`recommended` tags as the dedup corpus.

| Status | Milestone | Tasklist |
|---|---|---|
| ✅ | **JD ingest** — import a job description by **copy-paste or file upload** (parse `.txt`/`.md`/`.pdf`/`.docx` to plain text), normalize to one canonical JD document; a BYO-key-optional read path (plain text needs no model) | `chief/74-jd-ingest` |
| ✅ | **Requirement & skill extraction** — model-backed pass turning a JD into a structured list of required skills / tools / competencies, normalized leniently and graded strictly in the `curriculum_gen.py` house style (ask JSON, normalize, validate before use) | `chief/75-jd-requirement-extraction` |
| ✅ | **Gap analysis vs the library** — match extracted requirements against the existing 245 notebooks (14 domains) + the `recommended` neighbours, classifying each requirement as *covered* / *partially covered* / *missing*, reusing the `docs/explanation/gap-analysis.md` coverage model | `chief/76-jd-library-gap-analysis` |
| ✅ | **Suggestion + dedup engine** — turn *missing* / *partial* requirements into proposed subjects, deduplicated against existing topics and domains so no suggestion re-tutorials shipped material; each suggestion carries its source requirement and its gap rationale | `chief/77-jd-suggestion-dedup-engine` |
| ✅ | **Review / accept surface** — an in-app view to review, edit, drop, or accept suggestions; an accepted one becomes a subject handed to the shipped `POST /api/subjects` → scaffold → construct flow (no new constructor, just a new entry point) | `chief/78-jd-suggestion-review-surface` |

### Adopt the Jupyter grading ecosystem — ✅ shipped, **ran before the gating backfill**

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
| ✅ | **nbgrader cell schema + hidden-test mechanics** — emit `metadata.nbgrader` graded cells with stable `grade_id`s, adopt nbgrader's solution/hidden-test delimiters and release mechanics (deleting the reimplementation), carry `choice`/`short` as a namespaced extension, and make `nbgrader validate` the authoritative gate; the 24 already-gated seeds migrate by an idempotent pass · M/L | `chief/84-nbgrader-cell-schema-adoption` |
| ✅ | **JupyterLite delivery** — bundle a pinned JupyterLite site in the Tauri app so a learner reaches a running tutorial with zero terminals, zero `pip install` and zero kernel registration; serve only *released* (stripped) notebooks; keep the gate's authority out of the browser; report honestly when a tutorial's deps are not Pyodide-resolvable · M/L | `chief/85-jupyterlite-delivery` |

### Adopt, don't hand-roll — `chief/86` — ✅ all three stories landed (two of them in `chief/88`)

`chief/86` (category `replace`) bundled three independent cleanups. Its completed record marks all
three stories passing and it merged as `aa944fa` — **but that merge is 3 files, +26/−17, and carries
US-1 alone.** That was measured against the tree on 2026-09-11, not read off the record; the two
stories it left behind are built by `chief/88-finish-86-s3-client-and-llm-retry`, and the rows
below cite that branch's commits rather than a claim:

| Status | Milestone | Tasklist |
|---|---|---|
| ✅ | **Use the declared `nbformat`** — the production writers (`praxis/construct.py`, `scaffold_notebooks.py`) build cells with `nbformat.v4` and write with `nbformat.write` instead of hand-built dicts | `chief/86-adopt-minio-nbformat-and-delete-legacy` US-1 (`aa944fa`) |
| ✅ | **Replace the hand-rolled S3 client** — `praxis/s3.py` is a **249-line adapter over `minio.Minio`** (was 291 lines of hand-rolled SigV4, ListObjectsV2 XML and urllib; 193 removed), `minio>=7.2,<8` is a core dependency, and all four importers are byte-identical — `tests/mocks3.py` kept as the oracle, with its 16 S3/cloud assertions unedited. The story's other half — deleting the dead `generate_notebooks.py` / `enhance_notebooks.py` — was done earlier by `chief/900` (`b8858f5`) | `chief/86` US-2 — marked passing but **not done**; landed by `chief/88-finish-86-s3-client-and-llm-retry` US-1 (`fd6efaf`) |
| ✅ | **Real LLM retry semantics** — `LLMClient.complete()` retries inside a tenacity `Retrying` on 429, any 5xx (529 included) and connection-level failures, honouring `Retry-After` in both RFC 9110 forms, else bounded exponential backoff with jitter, under a 4-attempt / 45-second budget. `_urlopen` stays the one urllib seam, so the frozen direct wire and its four pinned error strings are unedited | `chief/86` US-3 — marked passing but **not done**; landed by `chief/88-finish-86-s3-client-and-llm-retry` US-2 (`684320d`) |

The `86` record is left as chief wrote it; **this table is the correction of record.**
`chief/88-finish-86-s3-client-and-llm-retry` (category `fix`) built the two rows it had marked
passing: minio-py behind `praxis.s3`'s existing surface with `tests/mocks3.py` kept as the oracle,
and tenacity-driven retry inside `praxis/llm.py`'s `complete()` with `_urlopen` kept as the urllib
seam. Both deliberately swapped one thing at a time — the client but not the test double, the retry
policy but not the transport — so the existing suites stayed the oracle for the swap. `chief/88`'s
own merge commit lands in `tasks/chief/completed/88-finish-86-s3-client-and-llm-retry.json` as
`mergedToMain` and reaches the merged-tasklist bullet below at the next reconcile.

### Gating backfill program — ✅ shipped and run (2026-08-27)

> **What actually happened, in order.** The band shipped its machinery — `backfill.py`, `coverage.py`,
> `gateaudit.py`, `regate.py` — and then **nobody ran it**: an 18-repo audit on 2026-08-25 found the
> library still at **24/245 in 8 of 14 domains**, with no tasklist owning the run itself. `chief/87`
> is that run. It found the reason the batches had sat: the batch is a grader wrapped around one
> HTTP call, so with no provider configured the *grading* — the part that is the product — was
> unreachable too. `praxis/authored.py` supplies the asking half from a draft on disk while every
> downstream refusal (`checkset_failures(verify_code=True)`, the triviality rules, `nbgrader
> validate`) runs unchanged.
>
> **Where it landed: 117/245 gated, in 14 of 14 domains.** Breadth first, as planned — the six
> domains that had no gate at all (`01`, `04`, `05`, `07`, `09`, `10`) went to 100%, because a real
> gate in every domain is worth more to a learner than an exhaustive one in three. The other 128 are
> in four partially-gated domains and are **deferred with a reason and a date** in
> `notebooks/ungated.json`, so ungated-by-choice is distinguishable from ungated-by-omission and the
> latter is **0**. Quality held: `gateaudit` flags **0 of 117** gates and `regate` reports 117/117
> holding today's tightened bar.

This program drove the ungated seeds toward gated by **reusing the shipped check machinery
unchanged** — `praxis/checks.py` over `GATED_SECTIONS`, and the derived-unlock gate in
`progress.py` — in per-domain batches rather than one sweep, with the anti-fabrication verification
(the reference `solution` run against its own `test` in a subprocess) held as the quality bar it
already enforces. It invented no gating primitive, and the run added none: `chief/87` changed the
*caller* (`praxis/authored.py`), never a rule.

**Retargeted 2026-08-11 by D10:** the format this band writes at scale is now the **nbgrader schema**
adopted in `chief/84`, not the parallel `<slug>.checks.json` sidecar it was originally written
against — backfilling 221 notebooks into a format about to be retired would be the most expensive
possible way to discover the adoption. All three rows therefore gain a hard dependency on `84`.

*Depends on:* `chief/84` (the schema and the `nbgrader validate` gate) plus the shipped **Gate**
(`40`) machinery — this phase ran it at scale, it invents no new gating primitive.

**Still open, deliberately:** the 128 notebooks in `02-ai-ml-tooling`, `08-architectures`,
`03-llm-inference-training-optimization` and `11-devops-mlops-infra`, in that queue order. The
constraint is authoring attention, not suitability, and the decision is recorded per domain with a
reason and a date rather than left as an absence — see `notebooks/ungated.json` and
`python3 -m praxis.ungated`.

| Status | Milestone | Tasklist |
|---|---|---|
| ✅ | **Batched gating program (by domain)** — the breadth-first per-domain batch, writing `84`'s nbgrader schema, skipping an already-✅ or already-gated notebook. Merged as machinery in `79`; **run** in `87`: six 0% domains → 100%, **24/245 → 117/245**, 8 of 14 domains → **14 of 14**, at a measured ~3 s of machine time per notebook | `chief/79-gating-backfill-by-domain` · run by `chief/87-run-the-gating-backfill` |
| ✅ | **Coverage tracker (X/245 gated)** — `praxis/coverage.py`, a fold over the launcher's own topic rows with **the per-domain fraction as the primary figure**, folded onto `/api/library` as `coverage` and rendered by both UIs. Now also a **ratchet**: `praxis/gatefloor.py` fails the merge gate when a domain or the library drops below `notebooks/coverage-floor.json`, and the README carries the figure a reader meets. The complement is split into **deferred** (`notebooks/ungated.json`) and **omitted**, which is 0 | `chief/80-gating-coverage-tracker` · ratchet + README claim in `chief/87` |
| ✅ | **Gate-quality / anti-fabrication pass** — `praxis/gateaudit.py` owns exactly the residue `nbgrader validate` cannot judge (an answer given away in its own prompt, a key quoted out of the notebook body, a test an empty submission or the starter stub passes, two near-identical prompts), thresholds measured against the 24 hand-built seeds; the same rules are on the **write path**, and `praxis/regate.py` re-audits gates written before the bar. Across all 117 gates: **0 flagged, 117/117 hold** | `chief/81-gate-quality-anti-fabrication` · verified over the backfilled set in `chief/87` |

### Chief-powered tutorial construction — ✅ shipped

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
| ✅ | **Chief-driven construction + gating** — run `construct_each` / `checks.py` batches as Chief tasklists on OpenCode + local inference (headless, resumable via the existing skip-if-✅ contract), so gating backfill and JD-suggested subjects build unattended and cheaply · depends on `chief:embeddable-engine` | `chief/82-chief-powered-construction` |

---

## Chief Tasklist Status

- **26/26 tasklists merged, 0 active, 0 retired** (measured 2026-09-11). Records in
  [`tasks/chief/completed/`](tasks/chief/completed/), each carrying its `mergedToMain` commit. The
  built program: `10-rebrand-and-tauri-shell` → `ef8c81d` · `20-user-defined-subjects` → `b6cce13` ·
  `30-agentic-construction` → `a7c23cb` · `40-gated-progression` → `509601f` ·
  `50-storage-integrations` → `707cc24` · `60-package-and-distribute` → `6ca7bef`. *(This bullet read
  "16 proposed forward tasklists authored … unrun", corrected-in-place 2026-08-25; rewritten 2026-09-11.)*
- **18 forward tasklists merged** (`70`–`87`), backing the **Planned / product-hardening**,
  JD-suggestion, **Jupyter-ecosystem adoption**, `86` replacement, gating-backfill,
  Chief-construction and seed-library-refresh phases above:
  `70` → `ed96395` · `71` → `6993db2` · `72` → `e005aad` · `73` → `e262757` · `74` → `4ee54b9` ·
  `75` → `49d966f` · `76` → `97fa811` · `77` → `3a7f1da` · `78` → `60eb1c8` · `79` → `f819be6` ·
  `80` → `ada1d1f` · `81` → `9a71a2d` · `82` → `9d0836c` · `83` → `d22667d` · `84` → `1aa111b` ·
  `85` → `6e55c3d` · `86` → `aa944fa` (**US-1 only** — its other two stories are built in `chief/88`,
  see its section) · `87` → `d1b4b59`. Of the
  loose wishlist rows, seed-library upkeep has its machinery from `chief/83` and the
  rubric-tightening thread carries no tasklist (`chief/81` shipped its measured rules); both stay
  open as upkeep. *(This bullet read "16 proposed tasklists … all now authored … unrun"; rewritten
  2026-09-11.)*
- **`chief/87-run-the-gating-backfill`** is the one tasklist that shipped no feature by design: it
  **ran** `79`–`81`'s merged machinery, which had sat unrun for a fortnight because every other
  tasklist in the program had an obvious code deliverable and this one did not. Coverage 24/245 →
  **117/245**, in 14 of 14 domains, `gateaudit` 0 flagged across all 117. What it did add is the
  three things that keep it from happening again: `praxis/authored.py` (the batch is runnable with
  an author where the model goes), `praxis/ungated.py` (a deferral is a dated record, not an
  absence) and `praxis/gatefloor.py` (coverage is a ratchet the merge gate holds, and the README
  states the figure a reader meets).
- **`chief/900-dead-code-paydown`** (`cccdf03`) and **`chief/901-docs-tell-the-truth`** (`03c30df`)
  are the closing sweeps. `900` removed the legacy generators (896 lines), `sync_curriculum.py`,
  `ralph/` + `.ralphy/` and four dead symbols, and recorded what it could not decide in
  [`docs/explanation/dead-code-inventory.md`](docs/explanation/dead-code-inventory.md); `901`
  banner-stamped and indexed every doc, and archived `technologies.md` rather than deleting it.
- **Scheduling note:** task numbers are stable identifiers, not execution order — `dependsOn` is
  authoritative. `chief/84` (nbgrader schema) had to run **before** `chief/79`–`81` despite its
  higher number, because those three write the schema it adopts; `chief/85` (JupyterLite) depends on
  `84` because it is `84`'s *released* notebooks that are safe to hand to an untrusted browser.
- The 6-tasklist built program is complete, and so is every forward tasklist above. `86`'s two
  unfinished stories — the S3 client and LLM retry — are built in `chief/88` (`fd6efaf`,
  `684320d`), so what is open is the 128 deferred notebooks and the two upkeep threads. *(This read
  "the 16 proposed forward tasklists above are authored but unrun"; rewritten 2026-09-11. The
  `86`-gap clause was removed 2026-09-12, when `chief/88` closed it.)* (Earlier offline notebook-filling runs used
  Ralph/ralphy — `ralph/`, `.ralphy/` — historical and superseded by the in-app construction
  agent from band 30; `chief/900` removed both trees, see
  [`docs/explanation/dead-code-inventory.md`](docs/explanation/dead-code-inventory.md) A7.)

---

## Related Docs

Reference contracts (living docs, kept in place):
- [`docs/explanation/notebook-rubric.md`](docs/explanation/notebook-rubric.md) — the definition of a complete tutorial
  (8 sections, runnable vs conceptual) and the knowledge-check rules; the shape of the gate.
- [`docs/reference/storage.md`](docs/reference/storage.md) — the one-root layout and the app / drive / cloud backends.
- [`docs/reference/packaging.md`](docs/reference/packaging.md) — desktop bundle + optional web build + CI contract.
- [`docs/explanation/gap-analysis.md`](docs/explanation/gap-analysis.md) — seed-library topic coverage and recommended additions.

Project orientation:
- [`README.md`](README.md) — install, the reusable core, and first-run.
- [`CLAUDE.md`](CLAUDE.md) — the authoritative build/test/quality gates and the module-by-module
  design of the construct → check → gate → storage pipeline.

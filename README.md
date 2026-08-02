# Praxis

**Praxis constructs interactive, gated notebook tutorials for any subject.**

You define a subject. AI agents build the tutorials to a defined rubric. The tutorials
gate progression behind knowledge checks, so a learner advances by demonstrating
understanding rather than by scrolling.

Praxis started life as `ai-tutor`, a static study-notebook library for refreshing a broad
span of technologies. That library is not thrown away — it is the machinery Praxis is
built on, plus 221 real notebooks that ship as the seed library and as worked examples of
what a finished tutorial looks like.

## The reusable core

Everything below already exists and is the foundation. Praxis extends it; it does not
replace it.

| Piece | Role in Praxis |
|-------|----------------|
| [`docs/notebook-rubric.md`](docs/notebook-rubric.md) | **The definition of a complete tutorial** — 8 sections, runnable vs conceptual. Construction agents fill to this bar; it is also the shape of the gated tutorial. |
| [`curriculum.py`](curriculum.py) | The curriculum model — the seed domains, and the data-driven subjects a user defines. |
| [`praxis/curriculum_gen.py`](praxis/curriculum_gen.py) | **Subject → curriculum** — free text in, modules → topics out, one notebook per topic. |
| [`scaffold_notebooks.py`](scaffold_notebooks.py) | **The scaffolder** — turns any curriculum's topic list, seed or generated, into 🔴 rubric-shaped notebook scaffolds. |
| [`nbstatus.py`](nbstatus.py) | **The gate (heuristic side)** — the status badge every topic carries: 🔴 scaffold · 🟡 partial · ✅ complete. |
| [`tests/test_notebooks.py`](tests/test_notebooks.py) | **The gate (authoritative side)** — a tutorial is complete only when this passes for it. |
| [`praxis/llm.py`](praxis/llm.py) | **The BYO-key LLM client** every construction step calls through (see below). |
| [`launcher/`](launcher/) | The FastAPI browse/launch/render UI. The desktop shell wraps this. |
| [`notebooks/`](notebooks/) | **221 seed notebooks across 10 domains** (+ the legacy DevOps/MLOps library). |
| [`CURRICULUM.md`](CURRICULUM.md) | Generated human index with live status badges. |
| [`ralph/`](ralph/README.md) | Tasklists that drive agents to fill notebooks autonomously. |
| [`src-tauri/`](src-tauri/) + [`ui/`](ui/) | The desktop/web shell — Rust backend, TS/React frontend. |

Notebooks live under `notebooks/<NN-domain>/<topic>.ipynb` and carry their Praxis state
under `metadata.praxis` (`status`, `runnable`, `recommended`). The original MLOps/AWS/GPU
library is preserved under [`notebooks/11-devops-mlops-infra/`](notebooks/11-devops-mlops-infra/).

## Architecture

- A **Tauri** desktop/web app: Rust backend in `src-tauri/`, TS/React frontend in `ui/`.
- The notebook-construction and gating core stays **Python** — it *is* the rubric,
  scaffolder, and gate above.
- **LLM access is bring-your-own-key**: provider and key come from config/env
  (OpenAI / Anthropic / local). An optional `AGORA_BASE_URL` can route through a
  provider-router. Never hardcode or commit a key. Praxis is standalone — no hard
  dependency on any other system.

- **Your data is yours and lives in one place**: subjects, tutorials and progress are
  written under a single storage root — your app-data directory by default, and one
  directory you can copy. See [docs/storage.md](docs/storage.md).

The subject-definition, AI-construction, gating, and storage capabilities land
incrementally; the core above is what they build on.

## LLM access (bring your own key)

[`praxis/llm.py`](praxis/llm.py) is the single place Praxis talks to a model. It uses
only the standard library, and it **never reads a key from source** — provider, key,
model, and endpoint come from the environment first, then from a JSON config file
(`$PRAXIS_CONFIG`, else `~/.config/praxis/config.json`).

Three direct providers, selected by `PRAXIS_LLM_PROVIDER` or inferred from whichever
credential is present:

```bash
export ANTHROPIC_API_KEY=...                        # -> anthropic, /v1/messages
export OPENAI_API_KEY=...                           # -> openai, /v1/chat/completions
export PRAXIS_LLM_BASE_URL=http://localhost:11434   # -> local OpenAI-compatible server
```

**Routing:** when **`AGORA_BASE_URL` is set, every call is routed through agora's
provider-router** (`<AGORA_BASE_URL>/v1/chat/completions`, authenticated with
`AGORA_API_KEY` if set, otherwise the provider key) instead of the provider's own
endpoint; the model string is passed through untouched, so set `PRAXIS_LLM_MODEL` to
whatever the router expects. When **`AGORA_BASE_URL` is unset, calls go direct** to the
provider. Praxis is standalone — agora is optional, never required.

Other knobs: `PRAXIS_LLM_MODEL` (overrides the per-provider default),
`PRAXIS_LLM_API_KEY` (overrides the provider-specific key variable).

```bash
python -m praxis.llm     # doctor: prints the resolved route, spends no tokens
```

Never commit a key. `tests/test_llm.py` covers every routing mode against a mocked
response, so the suite makes no network calls.

## The desktop shell

```bash
pip install -e '.[launch]'          # the shell runs the launcher behind the window
cd ui && npm ci && npm run build    # the frontend bundle src-tauri embeds
cd ../src-tauri && cargo run        # opens the Praxis window
```

The window opens on the **seed library**: subjects on the left, topics with their live
status badge (🔴 scaffold · 🟡 partial · ✅ complete), and *open* renders a notebook
read-only in place (*in Lab* points the same pane at JupyterLab, which needs
`praxis-lab` running). Subject definition and AI construction land in later steps.

Rust does not reimplement any of that: at boot it starts `launcher/app.py` on a free
loopback port and the webview reads `/api/library` and `/render/<rel>` from it (see
[`src-tauri/src/library.rs`](src-tauri/src/library.rs)). The launcher is found via
`$PRAXIS_PYTHON`, then `.venv/`, then `python3`; if it can't start, the window says
why. It is killed when the app exits, and stops itself if the app is killed hard.

Three things to know about how it builds:

- `src-tauri` embeds `ui/dist` at **compile** time, so build the frontend before the
  Rust side. `ui/dist` is generated, not committed; if it is missing, `src-tauri/build.rs`
  embeds a placeholder page so `cargo build` still succeeds on a fresh checkout — a green
  `cargo build` alone does not mean the real UI is inside.
- Embedding only happens with the `custom-protocol` feature, which is **on by default**
  here. Without it Tauri loads `build.devUrl` instead and the window is blank unless a
  Vite dev server is up. For frontend live-reload, turn it off:
  `npm --prefix ui run dev` plus `cargo run --no-default-features`.
- The window is defined in [`src-tauri/tauri.conf.json`](src-tauri/tauri.conf.json); the
  frontend talks to Rust through `invoke` (see [`ui/src/tauri.ts`](ui/src/tauri.ts)) and
  degrades to a plain browser preview when there is no backend — there it expects a
  hand-started `praxis-launch` (override with `VITE_PRAXIS_LAUNCHER`).

## Quick start (the launcher)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[launch,dev]'

# Terminal 1 — live notebooks (JupyterLab rooted at this repo, on :8888):
praxis-lab

# Terminal 2 — the launcher UI (subject sidebar, on :8000):
praxis-launch
```

Open <http://localhost:8000>: pick a subject on the left, then **open in Lab** to
edit/run the live notebook or **render** for a read-only HTML view. Each topic shows its
status badge (🔴 scaffold · 🟡 partial · ✅ complete).

## Defining a subject

Open the desktop shell, hit **define a subject**, and describe what you want to learn in
your own words. Praxis asks your model (see above — your key, your provider) for a
curriculum: modules, then one notebook per topic, each tagged runnable or conceptual. The
result is saved to `<storage root>/subjects/<slug>/curriculum.json` and shown for review
before any notebook is written. That root is your app-data directory by default — see
[docs/storage.md](docs/storage.md), or the path in the app's footer.

The same thing from a terminal:

```bash
python -m praxis.curriculum_gen "I want to navigate by the stars"
python -m praxis.curriculum_gen --modules 6 --topics 5 "conversational Portuguese"
python curriculum.py                # what is defined: seed domains + your subjects
```

### Scaffolding it

Reviewing is the point of the pause: nothing is written into the library until you hit
**Scaffold N notebooks**. That writes one notebook per topic under
`<storage root>/subjects/<slug>/<NN-module>/<topic>.ipynb`, each carrying the 8 rubric sections
as TODOs and `metadata.praxis.status = "scaffold"` — so it lands in the library badged 🔴,
ready for an agent (or you) to fill. It is safe to hit again: a topic that already has a
notebook is skipped, never rewritten, so re-scaffolding a grown curriculum only adds what
is missing.

```bash
python scaffold_notebooks.py --subject <slug>   # one defined subject
python scaffold_notebooks.py                    # seed manifest + every defined subject
python scaffold_notebooks.py --no-subjects      # seed manifest only
```

The launcher serves it over HTTP — this is what the shell calls:

| Route | |
|---|---|
| `GET /api/subjects` | every persisted subject, newest first |
| `GET /api/subjects/<slug>` | one curriculum, modules → topics |
| `POST /api/subjects` | `{"goal": "..."}` → generate + persist (spends tokens) |
| `POST /api/subjects/<slug>/scaffold` | the reviewed curriculum → 🔴 notebooks on disk |
| `GET /api/storage` | which backend is holding your work, and whether it's reachable |

A subject's modules are ordinary domains, so the scaffolder, the badges and the gate treat
them exactly like the seed library. Generated subjects are yours, not the product's: they
are written to your own storage root, outside the repo entirely
([docs/storage.md](docs/storage.md)).

To edit the **seed** curriculum instead, change [`curriculum.py`](curriculum.py)
(add/remove topics; `recommended=True` marks suggested additions), then:

```bash
python scaffold_notebooks.py        # scaffold new topics
python ralph/generate_tasklists.py  # rebuild the construction tasklists
python generate_docs.py             # refresh indices
```

## Constructing the tutorials

Notebooks are scaffolds until an agent fills them to the rubric. To fill them with
[ralphy](https://github.com/michaelshimeles/ralphy) (auto-commits per notebook):

```bash
./ralph/run.sh 8          # fill one subject (Architectures) — a good first smoke test
FAST=1 ./ralph/run.sh 8   # ...without the test/lint gate
./ralph/run.sh            # fill everything, subject by subject
```

See [`ralph/README.md`](ralph/README.md) for the full workflow. As notebooks are filled,
re-run `python generate_docs.py` to refresh the indices and badges.

## The gate

```bash
pytest                 # validates nbformat + enforces the rubric on completed tutorials
```

A tutorial is "complete" only when `nbstatus.py` reports ✅ **and**
`tests/test_notebooks.py` passes for it. Never flip a status on an unfilled notebook, and
never use placeholder URLs in Resources — they must be real links.

## Renaming note

The in-repo rebrand (package name, console scripts, notebook metadata key, docs) is done.
Two renames remain and are **manual owner steps, deliberately outside this repo's
automation**:

- renaming the GitHub repository `ai-tutor` → `praxis`, and
- renaming the local checkout directory.

Notebooks authored before the rebrand used a `metadata.ai_tutor` block; the seed library
has been migrated to `metadata.praxis`, and `nbstatus.py` still reads the old key as a
fallback so externally-authored legacy notebooks keep working.

## History

The legacy generators (`generate_notebooks.py`, `enhance_notebooks.py`,
`technologies.md`) are kept for history but are superseded by `curriculum.py` +
`scaffold_notebooks.py`.

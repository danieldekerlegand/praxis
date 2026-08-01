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
| [`curriculum.py`](curriculum.py) | Single source of truth for subjects (domains) and their topics. |
| [`scaffold_notebooks.py`](scaffold_notebooks.py) | **The scaffolder** — turns a subject's topic list into notebook scaffolds. |
| [`nbstatus.py`](nbstatus.py) | **The gate (heuristic side)** — the status badge every topic carries: 🔴 scaffold · 🟡 partial · ✅ complete. |
| [`tests/test_notebooks.py`](tests/test_notebooks.py) | **The gate (authoritative side)** — a tutorial is complete only when this passes for it. |
| [`launcher/`](launcher/) | The FastAPI browse/launch/render UI. The desktop shell wraps this. |
| [`notebooks/`](notebooks/) | **221 seed notebooks across 10 domains** (+ the legacy DevOps/MLOps library). |
| [`CURRICULUM.md`](CURRICULUM.md) | Generated human index with live status badges. |
| [`ralph/`](ralph/README.md) | Tasklists that drive agents to fill notebooks autonomously. |

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

The app shell and the subject-definition, AI-construction, gating, and storage
capabilities land incrementally; the core above is what they build on.

## Quick start

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

Edit [`curriculum.py`](curriculum.py) (add/remove topics; `recommended=True` marks
suggested additions), then:

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

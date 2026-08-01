# Praxis

A browsable, launchable **study-notebook library** for refreshing a broad span of
technologies — symbolic AI, ML tooling, LLM training/optimization, agents, speech,
graphics/VR, neural architectures, procedural generation, data/research, and the
existing DevOps/MLOps & infra library.

**221 notebooks across 10 domains.** They get filled to a defined rubric by the
[Ralph](ralph/README.md) tasklists.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[launch,dev]'

# Terminal 1 — live notebooks (JupyterLab rooted at this repo, on :8888):
ai-tutor-lab

# Terminal 2 — the launcher UI (categories sidebar, on :8000):
ai-tutor-launch
```

Open <http://localhost:8000>: pick a domain on the left, then **open in Lab** to edit/run
the live notebook or **render** for a read-only HTML view. Each topic shows a status badge
(🔴 scaffold · 🟡 partial · ✅ complete).

## How it's organized

| File | Role |
|------|------|
| [`curriculum.py`](curriculum.py) | **Single source of truth** — the 11 domains and their topics |
| [`CURRICULUM.md`](CURRICULUM.md) | Generated human index with live status badges |
| [`docs/gap-analysis.md`](docs/gap-analysis.md) | Coverage of the study list, recommended additions, and the legacy library |
| [`docs/notebook-rubric.md`](docs/notebook-rubric.md) | What "complete" means (the bar every notebook is held to) |
| [`scaffold_notebooks.py`](scaffold_notebooks.py) | Reorgs the legacy 64 + scaffolds new topics |
| [`generate_docs.py`](generate_docs.py) | Regenerates `CURRICULUM.md` + `docs/gap-analysis.md` |
| [`launcher/`](launcher/) | The FastAPI launcher UI |
| [`ralph/`](ralph/README.md) | ralphy tasklists that fill the notebooks autonomously |
| [`tests/test_notebooks.py`](tests/test_notebooks.py) | The automated completion gate |

Notebooks live under `notebooks/<NN-domain>/<topic>.ipynb`. The original MLOps/AWS/GPU
library is preserved under [`notebooks/11-devops-mlops-infra/`](notebooks/11-devops-mlops-infra/).

The legacy generators (`generate_notebooks.py`, `enhance_notebooks.py`, `technologies.md`)
are kept for history but are superseded by `curriculum.py` + `scaffold_notebooks.py`.

## Filling the notebooks (Ralph)

The notebooks ship as scaffolds. To fill them to the rubric with
[ralphy](https://github.com/michaelshimeles/ralphy) (auto-commits per notebook):

```bash
./ralph/run.sh 8          # fill one domain (Architectures) — good first smoke
FAST=1 ./ralph/run.sh 8   # ...without the test/lint gate
./ralph/run.sh            # fill everything, domain by domain
```

See [`ralph/README.md`](ralph/README.md) for the full workflow. As notebooks are filled,
re-run `python generate_docs.py` to refresh the indices and badges.

## Customizing the curriculum

Edit [`curriculum.py`](curriculum.py) (add/remove topics; `recommended=True` marks suggested
additions), then:

```bash
python scaffold_notebooks.py        # scaffold new topics
python ralph/generate_tasklists.py  # rebuild Ralph tasklists
python generate_docs.py             # refresh indices
```

## Tests

```bash
pytest                 # validates nbformat + enforces the rubric on completed notebooks
```

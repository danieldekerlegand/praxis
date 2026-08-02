# Ralph Tasklists — filling the study notebooks

Eleven [ralphy](https://github.com/michaelshimeles/ralphy) tasklists, one per domain.
Each has **one task per notebook that isn't complete yet**; ralphy fills the notebook to
[`docs/notebook-rubric.md`](../docs/notebook-rubric.md) and the gate in
[`tests/test_notebooks.py`](../tests/test_notebooks.py), committing after each task.

Each tasklist directory holds:

- `tasks.json` — the **ralphy-executable** file (`{project, description, tasks:[{title, description, completed}]}`).
- `prd.json` — the human-readable spec (story ids, acceptance criteria). Kept for reference; ralphy reads `tasks.json`.

Both are generated from [`curriculum.py`](../curriculum.py) by
[`generate_tasklists.py`](generate_tasklists.py) — never edit them by hand. Re-running the
generator drops notebooks that are already ✅ complete, so the tasklists shrink as you go.

| # | Domain | tasks.json |
|---|--------|-----------|
| 1 | Symbolic AI & Logic | `01-symbolic-ai-logic/tasks.json` |
| 2 | AI/ML Tooling | `02-ai-ml-tooling/tasks.json` |
| 3 | LLM Inference, Training & Optimization | `03-llm-inference-training-optimization/tasks.json` |
| 4 | Agentic AI | `04-agentic-ai/tasks.json` |
| 5 | Speech & Audio | `05-speech-audio/tasks.json` |
| 7 | Proprietary Models & Coding AI | `07-proprietary-coding-ai/tasks.json` |
| 8 | Architectures | `08-architectures/tasks.json` |
| 9 | Procedural Generation | `09-procedural-generation/tasks.json` |
| 10 | Data Analysis & Research | `10-data-analysis-research/tasks.json` |
| 11 | DevOps/MLOps & Infra (legacy) | `11-devops-mlops-infra/tasks.json` |

Counts drift as notebooks get filled — run `python ralph/generate_tasklists.py` to see current totals.

## Run them

```bash
# from the repo root — all domains in order
./ralph/run.sh

# or a subset by number (domains are independent — any order is fine)
./ralph/run.sh 8            # just Architectures
./ralph/run.sh 1 2 3

# quick smoke with no test/lint gate
FAST=1 ./ralph/run.sh 8
```

The runner auto-inits git if needed (ralphy commits per task), runs each tasklist with
`ralphy --json <file> --claude --max-retries 3`, and gates each domain on full completion
before the next. Completed tasks are skipped on re-run, so it resumes where it left off.

### Or call ralphy directly

```bash
ralphy --json ralph/08-architectures/tasks.json --claude
# parallel with worktree isolation (notebooks don't conflict):
ralphy --json ralph/08-architectures/tasks.json --claude --parallel --max-parallel 4
```

## Conventions every task assumes

- Single source of truth: `curriculum.py`. Rubric: `docs/notebook-rubric.md`. Gate: `tests/test_notebooks.py`.
- A task edits exactly one notebook and marks `metadata.praxis.status = "complete"` when done
  (legacy domain-11 notebooks instead just drop all placeholder text).
- "Runnable" topics need ≥2 executed code cells; "conceptual" topics use CLI/snippets with a clear note.
- Each task's `description` embeds its full rubric + acceptance criteria, so a fresh ralphy agent
  needs nothing else.

## Regenerating

After editing `curriculum.py` (adding/removing topics) or filling notebooks:

```bash
python scaffold_notebooks.py        # scaffold any newly-added topics
python ralph/generate_tasklists.py  # rebuild tasklists (drops completed notebooks)
python generate_docs.py             # refresh CURRICULUM.md + docs/gap-analysis.md
```

# Chief-powered construction — the batch, driven unattended and for free

> **Status:** Current · **Updated:** 2026-08-22 · **Owner:** praxis

Praxis builds a tutorial one model call at a time: define the subject, scaffold the
notebooks, construct each one to the rubric, write its gate. In the app that is a job you
watch. Across the seed library it is **221 ungated notebooks**, and nobody is going to sit
in front of that.

This is the mode that runs it with nobody in front of it: praxis emits a **Chief**
tasklist per unit of batch work and starts it **headlessly**, routed through **local
inference**, so the volume costs no API spend.

Two modules, and neither of them constructs anything:

| | |
|---|---|
| [`praxis/tasklist.py`](../../praxis/tasklist.py) | cuts the live library into **units** and writes `tasks/chief/<name>.json` |
| [`praxis/headless.py`](../../praxis/headless.py) | **starts** one of those tasklists as a Chief run and reads its outcome back |

The tasklist's stories run the shipped commands — `python3 -m praxis.backfill <dir>` and
`python3 -m praxis.construct --subject <slug>` — so what a Chief-driven run writes is what
an in-app run writes, because it is the same code path. Nothing in this mode is a second
definition of "complete".

## What it drives

A **unit** is one seed domain's gating backfill or one generated subject's build:

```console
$ python3 -m praxis.tasklist
gate-11-devops-mlops-infra          64 pending,   1 done  (python3 -m praxis.backfill 11-devops-mlops-infra)
gate-03-llm-inference-training-optimization  28 pending,   5 done  (…)
…
221 topics pending across 10 of 14 units
```

`python3 -m praxis.headless` turns that into a plan — the preset it resolved, the units it
would drive, and the exact argv it would run. It spawns nothing:

```console
$ python3 -m praxis.headless
preset  local → opencode · ollama/qwen2.5-coder:14b @ http://127.0.0.1:11434/v1

gate-11-devops-mlops-infra          64 pending,   1 done  (python3 -m praxis.backfill 11-devops-mlops-infra)
…
argv    chief run --headless --preset=local gate-11-devops-mlops-infra …
```

`run` starts it. A tasklist that is not on disk yet is generated first; one that is already
there is left exactly as it is, because its `passes` flags are Chief's bookkeeping.

```sh
python3 -m praxis.headless run gate-11-devops-mlops-infra   # one unit
python3 -m praxis.headless run --jd <jd-id>                 # the subjects accepted off a posting
python3 -m praxis.headless run -p 4                         # every unit with work, four at a time
```

Units declare the notebook tree they write (`touches`), so fourteen domain gates schedule
in parallel while two tasklists on the *same* domain never co-schedule.

## The cross-repo contract: `chief run --headless`

From **`chief:80-headless-programmatic-invocation`** (`docs/guides/headless-invocation.md`
in that repo). Headless is not a different engine — it is a flag that guarantees a
non-interactive shape and **adds machine-readable lines** to the stream:

```
chief: run-id=praxis-1234567890-1765000000-54321
chief: run-file=…      chief: events=…      chief: state=…
   … the human schedule and summary, for anyone watching …
chief: outcome=verify-failed
chief: exit=4
chief: summary={"runId":…,"outcome":"verify-failed","exit":4,"ok":false,"tasklists":[…]}
```

plus an exit code that names the outcome: `0` merged · `2` the run never started ·
`3` no work · `4` verify-failed · `5` conflict · `6` failed · `7` paused.

**Praxis reads those records and the exit status, and nothing else.**
`headless.records()` keeps `chief: <key>=<value>` lines and drops every other byte on the
stream; `parse_run()` takes the outcome from `chief: summary=`'s JSON, falling back to the
`chief: outcome=` line and then to the exit-code table — three machine-readable sources, in
order, and no fourth. The human summary block is prose written for a person and is free to
change; a host that scraped it would sooner or later report a merge that never happened.
So a stream carrying no `chief: run-id=` is an **error**, not something to interpret:

```
praxis.headless: no 'chief: run-id=' line on the stream and the run exited 0 —
either --headless was not passed or the driver is not chief; refusing to read an
outcome out of human output
```

The `run-id` is also what ties the run to Chief's own records — `chief ps`, the run file,
and the NDJSON event stream at `chief: events=` — so "what happened?" is answered from
Chief, not from a log praxis kept.

`chief` is found on `PATH`, or named by `PRAXIS_CHIEF`.

## The routing switch: local inference, and what it costs

From **`chief:82-local-inference-cost-avoidance-preset`**
(`docs/guides/local-inference-preset.md` in that repo). `chief run --preset local` runs
every agent turn on a **local / self-hosted OpenAI-compatible server** through OpenCode.
Praxis always passes it, and configures it from two variables:

| variable | |
|---|---|
| `CHIEF_LOCAL_ENDPOINT` | base URL of your server, e.g. `http://127.0.0.1:11434/v1` (Ollama) |
| `CHIEF_LOCAL_MODEL` | the model id to ask it for, e.g. `ollama/qwen2.5-coder:14b` |

`CHIEF_LOCAL_ENDPOINT_ENV`, `CHIEF_LOCAL_API_KEY` and `CHIEF_LOCAL_API_KEY_ENV` are
forwarded when set, and omitted when not. Praxis hard-codes no host — a default endpoint
would be a machine this code cannot see.

The preset **is** the provider choice, so praxis sends no `--provider` and no `--model`
next to it; Chief refuses that pair rather than guessing which one is paying.

### The tradeoff, stated where it is taken

**Lower coding quality, in exchange for zero marginal cost.** A model small enough to serve
from one machine writes materially worse code than a frontier model: it misreads multi-file
context, invents APIs, and satisfies acceptance criteria shallowly. That is the wrong trade
for a feature branch and the right one **here**, for one reason — every artifact this mode
produces passes through the shipped write-path gates before it lands:

- `construction_failures()` — the eight rubric sections, no placeholders, real `https://`
  Resources, code cells that `compile()`, the ✅ badge ([`praxis/rubric.py`](../../praxis/rubric.py));
- `checkset_failures(verify_code=True)` — every `code` check's reference solution run
  against its own test in a subprocess, plus the quality bar out of
  [`praxis/gateaudit.py`](../../praxis/gateaudit.py);
- `nbgrader validate` on a staging copy before graded cells are released.

Content that fails is **never written**. So a weaker model costs **iterations**, not
correctness: what it cannot get past the grader leaves the scaffold as it was, and the next
pass picks the topic up again. [`praxis/coverage.py`](../../praxis/coverage.py) counts what
actually landed, and it counts a topic only when both halves are on disk.

Praxis makes Chief's refusal one process earlier: with the preset unconfigured,
`praxis.headless` stops **before it generates a tasklist and before it spawns anything**,
rather than letting a run that was asked to be free reach a paid provider — a run that
cannot start leaves nothing behind on disk.

```console
$ python3 -m praxis.headless run gate-05-speech-audio
praxis.headless: the local-inference preset is not configured: CHIEF_LOCAL_ENDPOINT is not
set — …; CHIEF_LOCAL_MODEL is not set — …; refusing to run without the preset configured:
falling back to a paid provider is the one failure mode zero-cost construction must not have
```

## Why a retry is safe

Nothing about resumability is implemented in this mode. It **falls out** of two contracts
the batch already shipped with:

- **skip-if-✅** — `construct_topic` skips a notebook that already reports ✅ rather than
  rewriting it (`force=True` is the only way past, and nothing here passes it);
- **skip-if-gated** — `backfill.is_gated` does not even select a topic that has both its
  nbgrader graded cells and a loadable answer key.

So an unattended run that ran out of iterations, hit a verify failure, or was paused mid-
batch leaves a partially-gated domain, and re-running the same tasklist is a **resumed pass
over the remainder** — it cannot clobber a good notebook or a passing checkset. That is why
a tasklist's `iters` scales with its backlog: another iteration is another resumed pass, not
a harder story.

`praxis.headless` prints that remainder rather than making you work it out:

```console
run-id  praxis-1234567890-1765000000-54321
outcome verify-failed (exit 4)
  gate-05-speech-audio    verify-failed    VERIFY-FAILED
events  /Users/me/.chief/runs/praxis-….events.jsonl

re-run the remainder — a retry is a resumed pass, not a rewrite:
  python3 -m praxis.headless run gate-05-speech-audio
```

The CLI exits with **Chief's own exit code**, so a cron entry or a CI job wrapping praxis
branches on the same table Chief documents.

## What this mode does not do

- It does not construct or gate anything itself. Every rule about what "complete" means
  stays in `praxis/rubric.py`, `praxis/checks.py` and `praxis/gateaudit.py`.
- It does not import anything from the `chief` repo. The dependency is a documented CLI
  shape and two environment variables — a `chief` that ignored every one of them would
  fail loudly here, not silently produce a wrong answer.
- It does not read an API key. Praxis's own BYO-key path
  ([`praxis/llm.py`](../../praxis/llm.py)) is used by the agent Chief runs, inside the run's
  worktree, not by this wiring.
- It does not put a generated subject's notebooks in the branch. Those are the user's data
  and are written outside the repo under [storage](storage.md)'s root, so a `build-<slug>`
  tasklist's evidence is the recorded badge and gate counts, not a diff.

## See also

- [Storage — where your work is kept](storage.md) — where a generated subject's artifacts land.
- [Notebook Completion Rubric](../explanation/notebook-rubric.md) — the bar every constructed notebook clears.

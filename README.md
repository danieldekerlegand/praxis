# Praxis

**Praxis constructs interactive, gated notebook tutorials for any subject.**

You define a subject. AI agents build the tutorials to a defined rubric. The tutorials
gate progression behind knowledge checks, so a learner advances by demonstrating
understanding rather than by scrolling.

Praxis started life as `ai-tutor`, a static study-notebook library for refreshing a broad
span of technologies. That library is not thrown away — it is the machinery Praxis is
built on, plus 221 real notebooks that ship as the seed library and as worked examples of
what a finished tutorial looks like.

## Install

**Prerequisites.** Python ≥ 3.10 is the only hard one. The rest depend on how far you
want to go:

| you want | you need |
|---|---|
| the launcher UI in a browser | Python ≥ 3.10 |
| to **run** a tutorial's code cells | the same Python, with a Jupyter kernel — the `launch` extra pulls in JupyterLab and `ipykernel`, which registers the venv itself as the `python3` kernel (`jupyter kernelspec list` to confirm) |
| the desktop window | Node ≥ 18 and a Rust toolchain (see [the desktop shell](#the-desktop-shell)) |
| AI-defined subjects and AI-constructed tutorials | a model you can call — your own key, or a local server ([below](#llm-access-bring-your-own-key)) |

Browsing, rendering and knowledge checks need **no** model and no key. Only the two
writes that ask a model for content — defining a subject and constructing a tutorial —
plus grading a written (`short`) answer, do.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[launch,dev]'      # 'launch' = the UI + Jupyter; 'dev' = the test gate
```

Then, in two terminals:

```bash
praxis-lab       # live notebooks — JupyterLab rooted at this repo, on :8888
praxis-launch    # the launcher UI — subject sidebar, on :8000
```

Open <http://localhost:8000>: pick a subject on the left, then **open in Lab** to
edit/run the live notebook or **render** for a read-only HTML view. Each topic shows its
status badge (🔴 scaffold · 🟡 partial · ✅ complete). The desktop window
(`cargo run` in `src-tauri/`, or a [packaged bundle](#packaging--distribution)) starts
the same launcher for itself on a free port — you do not run `praxis-launch` by hand for it.

`praxis-lab` is only needed to *run* a notebook's code. The read-only render, the
library, and the gate all work without it.

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
  written under a single storage root — one directory you can copy. Keep it on this
  computer (the default), on a **drive** you pick, or in an **S3-compatible bucket**
  Praxis mirrors and syncs; choose in the app under *storage*. Switching only changes
  where Praxis looks — nothing is moved or deleted. See [docs/storage.md](docs/storage.md).

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
`PRAXIS_LLM_API_KEY` (overrides the provider-specific key variable), and
`PRAXIS_LLM_TIMEOUT` (seconds to wait for one reply, default 120). **Raise the timeout if
you point Praxis at a local model** — constructing a notebook is a single ~9000-character
reply, which a hosted provider streams in under a minute and a local 30B model can take
ten. Every one of these can also live in the config file instead.

```bash
python -m praxis.llm     # doctor: prints the resolved route + timeout, spends no tokens
```

Never commit a key. `tests/test_llm.py` covers every routing mode against a mocked
response, so the suite makes no network calls.

## First run, end to end

The whole loop is four steps, each one a separate, resumable write. Below is the
terminal form; the desktop window does the identical thing through
[the launcher's API](#the-launcher-api), and you can mix the two freely — they read the
same files.

```bash
export ANTHROPIC_API_KEY=...            # or OPENAI_API_KEY, or a local server (see above)
python -m praxis.llm                    # doctor: prints the route, spends no tokens
```

**1 — define.** Describe what you want to learn. The model answers with a curriculum;
nothing is written into the library yet.

```bash
python -m praxis.curriculum_gen --modules 2 --topics 2 \
    "I want to understand how Unix file permissions work"
```

That saves `<root>/subjects/<slug>/curriculum.json` — modules → topics, each topic
tagged runnable or conceptual. `<root>` is your storage root
([below](#where-your-work-is-kept)); `python curriculum.py` lists what is now defined.

**2 — scaffold.** Review the curriculum, then turn it into notebooks:

```bash
python scaffold_notebooks.py --subject <slug>
```

One notebook per topic, each carrying the eight rubric sections as TODOs and badged 🔴.
Spends no tokens. Safe to repeat — an existing notebook is skipped, never rewritten.

**3 — construct.** Fill the scaffolds to the rubric, and write the knowledge checks that
gate them:

```bash
python -m praxis.construct --subject <slug>
```

One model call per notebook, plus one for its checks. Content that fails the grader is
never written, and an already-✅ notebook is skipped — so a run that dies halfway is
resumed by running it again. Watch the badges move to ✅ in the launcher.

**4 — learn.** Open the notebook. Every rubric section except *Setup* and *Resources* is
gated: answer a section's checks to unlock the next one, and finish a topic to unlock the
next topic in the module ([below](#gated-learning)). Your answers are recorded under
`<root>/progress/`, so they survive quitting the app.

Prerequisites worth calling out before you start:

- **A Jupyter kernel** for step 4 if you want to *run* the code cells — `praxis-lab`,
  from the `launch` extra. Reading and answering checks need no kernel.
- **A model** for steps 1 and 3. Steps 2 and 4 make no model call at all, except for
  grading a `short` (written) answer.
- **Somewhere to put it.** The default is this computer's app-data directory and needs
  no setup; pick a drive or a bucket first if you want one ([below](#where-your-work-is-kept)),
  because switching later changes only where Praxis *looks* — it moves nothing.

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

Both steps are also HTTP — `POST /api/subjects` and `POST /api/subjects/<slug>/scaffold`
are what the desktop shell calls, and what a script can call instead
([the full route table](#the-launcher-api)).

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

A scaffold is eight empty sections. [`praxis/construct.py`](praxis/construct.py) fills
them: it asks your model for the notebook's cells, **grades the result against the
rubric, and only then writes**.

```bash
python -m praxis.construct --subject <slug>       # a whole curriculum, resumably
python -m praxis.construct <path/to/topic.ipynb>  # one notebook (repeatable)
python -m praxis.construct --force <path>         # rebuild an already-complete one
python -m praxis.construct --no-checks <path>     # notebook only, no gate
python -m praxis.construct --execute <path>       # also run it through nbconvert
```

In the app it is the same thing behind a button: `POST /api/construct` takes `{rel}`,
`{domain}` or `{subject}` and answers **202 with a job**, because it is one model call
per notebook; the shell polls it and the badges move 🔴 → ✅ as each one lands. One run
at a time.

Two rules do the anti-fabrication work, and they are why a long run is safe to interrupt:

- **Content that fails the grader is never written.** The scaffold survives untouched and
  the grader's own sentences come back as the failures, which is also the text the UI
  shows and the text fed back to the model for a repair attempt.
- **An already-✅ notebook is skipped, not rewritten** (unless `--force`), so re-running
  across a curriculum resumes instead of clobbering — including work you filled in by hand.

The grader is [`praxis/rubric.py`](praxis/rubric.py), shared with the test gate. For
construction it is stricter than for the seed library, by exactly the three things a model
will fake: the ✅ badge, `https://` Resource links that are real, and code cells that
compile.

Each constructed notebook also gets its [knowledge checks](#gated-learning) written beside
it — that second half is what makes it a *gated* tutorial rather than a finished one.

Filling notebooks with an autonomous coding agent instead, via
[ralphy](https://github.com/michaelshimeles/ralphy) (auto-commits per notebook):

```bash
./ralph/run.sh 8          # fill one subject (Architectures) — a good first smoke test
FAST=1 ./ralph/run.sh 8   # ...without the test/lint gate
./ralph/run.sh            # fill everything, subject by subject
```

See [`ralph/README.md`](ralph/README.md) for the full workflow. As notebooks are filled,
re-run `python generate_docs.py` to refresh the indices and badges.

## Gated learning

A constructed tutorial is gated. Every rubric section except *Setup* and *Resources*
carries checks, and **a section unlocks when every check in every earlier section has
been passed**; the same rule one level up orders a module's topics — you reach topic 2 by
finishing topic 1. Nothing about that is stored. The unlock state is
re-derived from your recorded answers on every request, so there is no flag to set, and a
check you later fail genuinely re-locks what it had opened.

The questions live *beside* the notebook as `<slug>.checks.json`
([`praxis/checks.py`](praxis/checks.py)), never inside it — the answer key must not sit in
a cell you are reading. Three kinds, all gradable without a human:

| kind | how it is graded |
|---|---|
| `choice` | multiple choice, against the key — locally, no model |
| `code` | your code is run together with the check's assertion in a subprocess; non-zero exit fails — locally, no model |
| `short` | a written answer, graded by your model, and recorded verbatim |

So learning needs no key at all unless you answer a `short` question. A `code` check's
reference solution is *run against its own test* before the set may be written, so
"auto-graded" can never mean "asserts nothing".

Two boundaries are enforced on the server, not in the UI: a locked section serves **no
questions at all**, and answering one you have not reached is refused **423** without
being graded. A disabled button is not the gate. `answer`, `solution`, `test` and
`expected` never cross to a client, and `explanation` only after you have answered.

A topic with no `<slug>.checks.json` gates nothing — which is what keeps the 221 seed
notebooks freely browsable. Gating appears exactly where the constructor wrote questions.

Your progress is one JSON file per learner under `<root>/progress/`, holding the whole
outcome — your answer included, not a boolean.

## Where your work is kept

Everything Praxis writes for you — the subjects you define, the tutorials constructed into
them, their checks, and your progress — lands under **one root** you can copy:

```
<root>/subjects/<slug>/curriculum.json · <NN-module>/<topic>.ipynb + <topic>.checks.json
<root>/progress/<learner>.json
```

The seed `notebooks/` are not that; they ship with the app and are never written to.
Three backends ship, differing only in where the root is:

| backend | root | |
|---|---|---|
| `app` *(default)* | this computer's app-data directory | private, no setup |
| `drive` | the folder you pick, verbatim | an external disk, a share, a synced folder |
| `cloud` | a local mirror, synced with an S3-compatible bucket | AWS, MinIO, R2, B2 — and still writable offline |

Choose one in the app under **storage** (the form is generated from what the backend
declares, and a stored secret is reported as "set", never given back), or:

```bash
python -c 'from praxis import storage; storage.select_backend("drive", {"path": "/Volumes/Backup/Praxis"})'
```

Switching changes **where Praxis looks** — it never copies, moves or deletes anything, so
the root you leave is exactly as you left it if you switch back. If the backend is not
reachable (drive unplugged), Praxis refuses every write with a 503 and tells you which
one it wants, rather than quietly writing somewhere else. Full contract, including the
cloud merge rule: **[docs/storage.md](docs/storage.md)**.

## The launcher API

[`launcher/app.py`](launcher/app.py) is the whole product over HTTP; the desktop shell is
a window onto it, and holds no logic of its own.

| Route | |
|---|---|
| `GET /api/library` | the whole library — domains, topics, live badges, gate state |
| `GET /api/subjects` | every persisted subject, newest first |
| `GET /api/subjects/<slug>` | one curriculum, modules → topics |
| `POST /api/subjects` | `{"goal": "..."}` → generate + persist (spends tokens) |
| `POST /api/subjects/<slug>/scaffold` | the reviewed curriculum → 🔴 notebooks on disk |
| `POST /api/construct` | `{rel}` \| `{domain}` \| `{subject}` → **202** + a job (spends tokens) |
| `GET /api/construct` · `GET /api/construct/<id>` | runs, newest first · one run's live progress |
| `GET /api/study/<rel>` | one topic's gate for one learner — locked sections carry no questions |
| `POST /api/study/<rel>` | `{"check_id": …, "answer": …}` → graded, recorded; **423** if not reached |
| `GET /api/storage` | which backend is holding your work, and whether it's reachable |
| `POST /api/storage` | `{"kind": "drive", "options": {...}}` → keep it somewhere else |
| `POST /api/storage/sync` | push/pull the cloud backend's mirror |
| `GET /render/<rel>` | a notebook, rendered read-only |

## The desktop shell

```bash
pip install -e '.[launch]'          # the shell runs the launcher behind the window
cd ui && npm ci && npm run build    # the frontend bundle src-tauri embeds
cd ../src-tauri && cargo run        # opens the Praxis window
```

The window opens on the library: subjects on the left, topics with their live status badge
(🔴 scaffold · 🟡 partial · ✅ complete), and *open* renders a notebook read-only in place
(*in Lab* points the same pane at JupyterLab, which needs `praxis-lab` running). Defining
a subject, constructing it, answering its knowledge checks and choosing a storage backend
are all in the window too — it is the [first-run loop](#first-run-end-to-end) with buttons
instead of a terminal.

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

## Packaging & distribution

A release build of the desktop app, from the repo root:

```bash
npm --prefix ui ci                      # the Tauri CLI ships as a frontend dev dependency
npm --prefix ui exec -- tauri build     # rebuilds ui/dist, then bundles
```

On macOS that writes `src-tauri/target/release/bundle/macos/Praxis.app` and
`bundle/dmg/Praxis_<version>_<arch>.dmg`; Windows and Linux emit their own installers from
the same command (each OS builds its own — nothing is cross-compiled). The bundle is the
*shell*: it starts the Python core at runtime rather than embedding it, so the checkout
and its `.venv` still need to be there (or `PRAXIS_ROOT` / `PRAXIS_PYTHON` set).

There is also an **optional web target** — `npm --prefix ui run build` serves `ui/dist`
from any static server on `localhost` against a hand-started `praxis-launch`, and
`praxis-launch` alone serves its own HTML with no build step at all.

Artifact paths per OS, prerequisites, signing status and the CI gate:
**[docs/packaging.md](docs/packaging.md)**.

Every PR to `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml), which
mirrors `.chief/verify.sh`: `npm run build`, `cargo build`, and `pytest tests/`, each
scoped to what the PR touched.

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

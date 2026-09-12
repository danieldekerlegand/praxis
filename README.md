# Praxis

**Praxis constructs interactive, gated notebook tutorials for any subject.**

You define a subject. AI agents build the tutorials to a defined rubric. The tutorials
gate progression behind knowledge checks, so a learner advances by demonstrating
understanding rather than by scrolling.

Praxis started life as `ai-tutor`, a static study-notebook library for refreshing a broad
span of technologies. That library is not thrown away — it is the machinery Praxis is
built on, plus 245 real notebooks that ship as the seed library and as worked examples of
what a finished tutorial looks like.

**Gate coverage: 117 of the 245 seed tutorials gate progression (48%), across 14 of 14 domains.**

The remaining 128 are ungated by a **recorded decision**, not by omission — each is
covered by a dated entry in [`notebooks/ungated.json`](notebooks/ungated.json) saying why
it is waiting, and the number of ungated notebooks with nothing on record is **0**. A seed
notebook with no checks browses freely rather than gating progression, by design.

That headline is a measurement, and it is enforced in both directions. `python3 -m
praxis.coverage` prints the per-domain breakdown — the primary figure, because coverage
everywhere is what the gate is worth to a learner — and `python3 -m praxis.gatefloor`
fails the merge gate if coverage ever drops below the number stated above, so the claim
cannot go stale the way it did while the library sat at 24/245.

**[`docs/`](docs/README.md) is the map** — every document this repo keeps is linked from
there, and one that is not linked there does not exist.

## Install

### If you are here to learn: open the app

A learner installs **nothing**. The desktop bundle carries its own tutorial runtime — a
[JupyterLite](https://github.com/jupyterlite/jupyterlite) site on a Pyodide kernel, which
is CPython compiled to WebAssembly — so reading a tutorial *and running its code cells*
needs no Python on the machine, no `pip install`, and no Jupyter kernel to register
([docs/reference/jupyterlite.md](docs/reference/jupyterlite.md)).

1. Open **Praxis.app** ([build one](#packaging--distribution) — on first launch macOS
   Gatekeeper wants a right-click → *Open*).
2. Pick a tutorial and hit **run**. It opens in the window, on the in-browser kernel.

That is the whole first run, measured against what it replaced:

| to reach a first running tutorial | before | now |
|---|---|---|
| steps | 7 | 2 |
| terminals | 2 | 0 |
| Python installs · kernel registrations | 1 · 1 | 0 · 0 |

(The seven were: install Python, create a venv, `pip install -e '.[launch,dev]'`, run
`praxis-lab`, run `praxis-launch` in a second terminal, open `localhost:8000`, pick a
topic and *open in Lab*.)

Two honest caveats, neither of them a step:

- The pinned kernel fetches Pyodide from a CDN the **first** time it runs, so a first run
  needs network; everything after it is cached.
- Pyodide has numpy, pandas, matplotlib, scipy and scikit-learn; it does not have `torch`
  or `transformers`. **101 of the 245 seed tutorials run in the browser.** The rest are
  listed as *unavailable in the browser*, naming the modules that made it so, rather than
  opened and left to fail at their first import.

### If you are here to build tutorials: install the core

Constructing a tutorial is a **model-backed write** — it asks a model for the notebook's
cells, grades the result against the rubric, and writes only what passes. That needs the
Python core and a key, and this is the line the app draws too: *reading and answering need
nothing; constructing does.*

| you want | you need |
|---|---|
| read a tutorial and **run** its code | nothing — it ships in the app |
| knowledge checks, progression, the live 🔴/🟡/✅ badges | the Python core: an [embedded bundle](docs/reference/packaging.md#the-python-runtime-in-the-bundle) carries it, otherwise a checkout with the `launch` extra beside the app |
| AI-defined subjects and AI-constructed tutorials | that same core **and** a model you can call — your own key, or a local server ([below](#llm-access-bring-your-own-key)) |
| to build the desktop window from source | Node ≥ 18 and a Rust toolchain (see [the desktop shell](#the-desktop-shell)) |
| to author notebooks by hand in a full JupyterLab | `praxis-lab`, from the `launch` extra |

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[launch,dev]'      # 'launch' = the UI + Jupyter; 'dev' = the test gate
```

Browsing, rendering and knowledge checks need **no** model and no key. Only the two
writes that ask a model for content — defining a subject and constructing a tutorial —
plus grading a written (`short`) answer, do.

### The contributor/authoring path (two terminals, as before)

This is what the learner path above replaced; it is still how you author and debug the
core, and nothing about it changed:

```bash
praxis-lab       # live notebooks — JupyterLab rooted at this repo, on :8888
praxis-launch    # the launcher UI — subject sidebar, on :8000
```

Open <http://localhost:8000>: pick a subject on the left, then **render** for a read-only
HTML view or **open in Lab** to edit and run the live notebook. Each topic shows its
status badge (🔴 scaffold · 🟡 partial · ✅ complete). The desktop window
(`make run`, or a [packaged bundle](#packaging--distribution)) starts the launcher for
itself on a free port and serves the JupyterLite site beside it — you run neither by hand
for it.

`praxis-lab` is only needed to *edit* a notebook or to run one Pyodide cannot serve. The
read-only render, the library, the gate, and running the 101 browser-ready tutorials all
work without it.

## The reusable core

Everything below already exists and is the foundation. Praxis extends it; it does not
replace it.

| Piece | Role in Praxis |
|-------|----------------|
| [`docs/explanation/notebook-rubric.md`](docs/explanation/notebook-rubric.md) | **The definition of a complete tutorial** — 8 sections, runnable vs conceptual. Construction agents fill to this bar; it is also the shape of the gated tutorial. |
| [`curriculum.py`](curriculum.py) | The curriculum model — the seed domains, and the data-driven subjects a user defines. |
| [`praxis/curriculum_gen.py`](praxis/curriculum_gen.py) | **Subject → curriculum** — free text in, modules → topics out, one notebook per topic. |
| [`scaffold_notebooks.py`](scaffold_notebooks.py) | **The scaffolder** — turns any curriculum's topic list, seed or generated, into 🔴 rubric-shaped notebook scaffolds. |
| [`nbstatus.py`](nbstatus.py) | **The gate (heuristic side)** — the status badge every topic carries: 🔴 scaffold · 🟡 partial · ✅ complete. |
| [`tests/test_notebooks.py`](tests/test_notebooks.py) | **The gate (authoritative side)** — a tutorial is complete only when this passes for it. |
| [`praxis/llm.py`](praxis/llm.py) | **The BYO-key LLM client** every construction step calls through (see below). |
| [`launcher/`](launcher/) | The FastAPI browse/launch/render UI. The desktop shell wraps this. |
| [`notebooks/`](notebooks/) | **245 seed notebooks across 14 domains** (including the legacy DevOps/MLOps library). |
| [`docs/reference/curriculum.md`](docs/reference/curriculum.md) | Generated human index with live status badges. |
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
  computer (the default), on a **drive** you pick, or in an **S3-compatible bucket** or a
  **WebDAV share** Praxis mirrors and syncs; choose in the app under *storage*. Switching only changes
  where Praxis looks — nothing is moved or deleted. See [docs/reference/storage.md](docs/reference/storage.md).

The subject-definition, AI-construction, gating, and storage capabilities land
incrementally; the core above is what they build on.

## LLM access (bring your own key)

[`praxis/llm.py`](praxis/llm.py) is the single place Praxis talks to a model. Its transport
is the standard library's — one `urllib` seam — with [tenacity](https://github.com/jd/tenacity)
driving the retry loop around it, and it **never reads a key from source** — provider, key,
model, and endpoint come from the environment first, then from a JSON config file
(`$PRAXIS_CONFIG`, else `~/.config/praxis/config.json`).

> **[CORRECTED 2026-09-12 — this paragraph said llm.py "uses only the standard library".
> That was true until `chief/88` gave the client real retry semantics: a **429** or a
> **5xx** is the provider asking us to wait, and burning a repair attempt on it in
> milliseconds is not an answer. tenacity now drives the loop (the one non-stdlib import
> there); the transport did *not* change, which is what keeps the direct wire frozen.]**

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

With the router in the path, two more optional knobs steer it and one more thing comes
back: `AGORA_ROUTE` asks for a named route/profile and `AGORA_FALLBACK_MODELS` (a
comma-separated list) names the models it may fall back to. Both ride in `x-agora-*`
**headers**, never in the request body, so they can never become a parameter the
upstream model rejects. What the router actually served — model, upstream provider,
resolved route, request id — is read back off the reply into `LLMClient.last_route`
(`client.route_description()`), so a fallback the router chose is visible instead of
silent, and a router failure is reported as the *router's*, with its own error message
and a reminder that unsetting `AGORA_BASE_URL` goes direct. None of it is required: a
router that reports nothing behaves exactly like the plain base-URL swap.

Other knobs: `PRAXIS_LLM_MODEL` (overrides the per-provider default),
`PRAXIS_LLM_API_KEY` (overrides the provider-specific key variable), and
`PRAXIS_LLM_TIMEOUT` (seconds to wait for one reply, default 120). **Raise the timeout if
you point Praxis at a local model** — constructing a notebook is a single ~9000-character
reply, which a hosted provider streams in under a minute and a local 30B model can take
ten. Every one of these can also live in the config file instead.

**Retries** are the client's, not the caller's: a **429**, any **5xx** (Anthropic's 529
included) and a connection-level failure are retried; every other 4xx and every malformed
reply fail at once. A wait is the server's `Retry-After` when it sends one, else
exponential backoff with jitter — and the whole call is bounded by
`PRAXIS_LLM_RETRY_ATTEMPTS` (default 4, the first call included) **and**
`PRAXIS_LLM_RETRY_BUDGET` (default 45 seconds, sleeps included), whichever runs out
first. The budget is short on purpose: grading a `short` answer runs through this client
inside a web request. A bad value in either is an error, not a silent fallback.

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

- **Nothing extra for step 4.** Running a tutorial's code cells is the bundled
  JupyterLite runtime's job — no kernel, no local Python. `praxis-lab` is only for a
  tutorial Pyodide cannot serve, or for editing one by hand.
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
[docs/reference/storage.md](docs/reference/storage.md), or the path in the app's footer.

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
([docs/reference/storage.md](docs/reference/storage.md)).

To edit the **seed** curriculum instead, change [`curriculum.py`](curriculum.py)
(add/remove topics; `recommended=True` marks suggested additions), then:

```bash
python scaffold_notebooks.py  # scaffold new topics
python generate_docs.py       # refresh indices
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

To drive that same loop unattended, [`praxis/tasklist.py`](praxis/tasklist.py) cuts the live
library into one-domain units and emits Chief tasklists that run the **shipped** commands, and
[`praxis/headless.py`](praxis/headless.py) starts them and reads the result back
([docs/reference/chief-powered-construction.md](docs/reference/chief-powered-construction.md)).
As notebooks are filled, re-run `python generate_docs.py` to refresh the indices and badges.

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

A topic with no `<slug>.checks.json` gates nothing — which is what keeps the 245 seed
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
**Four** backends ship, differing only in where the root is:

| backend | root | |
|---|---|---|
| `app` *(default)* | this computer's app-data directory | private, no setup |
| `drive` | the folder you pick, verbatim | an external disk, a share, a synced folder |
| `cloud` | a local mirror, synced with an S3-compatible bucket | AWS, MinIO, R2, B2 — and still writable offline |
| `webdav` | a local mirror, synced with a WebDAV share | Nextcloud, ownCloud, Synology, Box, `rclone serve webdav` — offline-writable the same way |

> **[CORRECTED 2026-09-03 — this said "Three backends ship" and listed three. `webdav`
> shipped alongside them (`praxis/share.py` over `praxis/webdav.py`, registered through
> the public `register_backend()` seam) and this table never grew the row.
> `docs/reference/storage.md` has had four all along, which is the two-copies-of-one-fact
> failure this table is: the contract is that page, and this is a summary of it.]**

Choose one in the app under **storage** (the form is generated from what the backend
declares, and a stored secret is reported as "set", never given back), or:

```bash
python -c 'from praxis import storage; storage.select_backend("drive", {"path": "/Volumes/Backup/Praxis"})'
```

Switching changes **where Praxis looks** — it never copies, moves or deletes anything, so
the root you leave is exactly as you left it if you switch back. If the backend is not
reachable (drive unplugged), Praxis refuses every write with a 503 and tells you which
one it wants, rather than quietly writing somewhere else. Full contract, including the
cloud merge rule: **[docs/reference/storage.md](docs/reference/storage.md)**.

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
| `GET /api/jd` · `GET /api/jd/<id>` | imported job descriptions — summaries · one, with its canonical text |
| `POST /api/jd` | `{"text": "..."}` → a pasted posting, normalized and persisted (no key needed) |
| `POST /api/jd/upload?filename=` | the file's raw bytes — `.txt`/`.md`/`.pdf`/`.docx` → the same document |
| `GET /api/jd/<id>/suggestions` · `POST` | one posting's tutorial suggestions — read the reviewed set · (re)build it from the extraction → gap → suggestion funnel (spends tokens) |
| `PUT` \| `PATCH` \| `DELETE /api/jd/<id>/suggestions/<sid>` | edit one suggestion's goal · the same · drop it |
| `POST /api/jd/<id>/suggestions/<sid>/accept` | → **201** and a subject generated from that goal (spends tokens) |
| `POST /api/jd/<id>/suggestions/<sid>` | `{"action": "edit"\|"drop"\|"accept"}` — the same three, for a client that uses one mutation verb |
| `GET /api/storage` | which backend is holding your work, and whether it's reachable |
| `POST /api/storage` | `{"kind": "drive", "options": {...}}` → keep it somewhere else |
| `POST /api/storage/sync` | push/pull the mirror of whichever syncing backend is active (`cloud` or `webdav`) |
| `GET /render/<rel>` | a notebook, rendered read-only |
| `GET /healthz` | the liveness probe the desktop shell waits on before it opens the window |

> **[CORRECTED 2026-09-03 — this table introduces itself as "the whole product over HTTP"
> and was missing the seven JD-suggestion routes (`chief/77`–`78`) and `/healthz`. A route
> table that is silently partial is worse than none: a reader concludes the endpoint does
> not exist. `launcher/app.py`'s decorators are the source; this table is now checked
> against them rather than appended to.]**

## The desktop shell

```bash
pip install -e '.[launch]'          # the shell runs the launcher behind the window
cd ui && npm ci && npm run build    # the frontend bundle src-tauri embeds
cd ../src-tauri && cargo run        # opens the Praxis window
```

The window opens on the library: subjects on the left, topics with their live status badge
(🔴 scaffold · 🟡 partial · ✅ complete), and *open* renders a notebook read-only in place
(*run* opens it live in the same pane on the bundled in-browser kernel, and says which
modules are missing when Pyodide cannot serve it). Defining
a subject, constructing it, answering its knowledge checks and choosing a storage backend
are all in the window too — it is the [first-run loop](#first-run-end-to-end) with buttons
instead of a terminal.

Rust does not reimplement any of that: at boot it starts `launcher/app.py` on a free
loopback port and the webview reads `/api/library` and `/render/<rel>` from it (see
[`src-tauri/src/library.rs`](src-tauri/src/library.rs)). The launcher is found via
`$PRAXIS_PYTHON`, then `.venv/`, then `python3`; if it can't start, the window says
why. It is killed when the app exits, and stops itself if the app is killed hard.

Beside it, on a second loopback port, the shell serves the **JupyterLite site** the bundle
carries ([`src-tauri/src/lite.rs`](src-tauri/src/lite.rs)) — a read-only static file
server over one directory, and the thing that makes *run* work with no Python at all. The
two are deliberately independent: when the Python core is missing or fails to start, the
window falls back to browsing and running that site, and names what it therefore cannot
do (knowledge checks, progression, construction) instead of showing an empty library.

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
npm --prefix ui ci      # the Tauri CLI ships as a frontend dev dependency
make bundle             # JupyterLite site -> rebuild ui/dist -> bundle
```

On macOS that writes `src-tauri/target/release/bundle/macos/Praxis.app` and
`bundle/dmg/Praxis_<version>_<arch>.dmg`; Windows and Linux emit their own installers from
the same command (each OS builds its own — nothing is cross-compiled).

Use `make bundle` rather than the bare command: it builds the **JupyterLite site** first
and passes the overlay config that copies it into the bundle, which is what makes the
learner path above need no Python. The Python core is still started at runtime, so
knowledge checks and construction want the checkout and its `.venv` beside the app (or
`PRAXIS_ROOT` / `PRAXIS_PYTHON` set) unless the bundle was built with
[an embedded runtime](docs/reference/packaging.md#the-python-runtime-in-the-bundle).

There is also an **optional web target** — `npm --prefix ui run build` serves `ui/dist`
from any static server on `localhost` against a hand-started `praxis-launch`, and
`praxis-launch` alone serves its own HTML with no build step at all.

Artifact paths per OS, prerequisites, signing status and the CI gate:
**[docs/reference/packaging.md](docs/reference/packaging.md)**.

Every PR to `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml), which
mirrors `.chief/verify.sh` check for check, each scoped to what the PR touched — the list
is under [The gate](#the-gate).

## The gate

[`.chief/verify.sh`](.chief/verify.sh) is the merge gate and the one home of the list;
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) mirrors it check for check, with
the same path predicates, so a change to one is a change to both. Six checks, each run
only when the diff touches what it covers:

| check | scope |
|---|---|
| `node scripts/check-doc-links.mjs --ratchet --base <base>` | any `.md` — every local reference resolves; a **ratchet**, so only a regression blocks |
| `node scripts/check-docs-structure.mjs` | any `.md` — every `docs/` file linked from [`docs/README.md`](docs/README.md) and banner-stamped, the directory set closed, and the repo root Tier-1 only; a **wall** |
| `npm run build` in `ui/` | `ui/` |
| `cargo build` in `src-tauri/` | `src-tauri/` (the frontend builds first — `src-tauri` embeds `ui/dist` at compile time) |
| `python scripts/validate_nbgrader.py notebooks` · `python -m praxis.gatefloor` · `python -m pytest -q tests/` | any Python, notebook, `scripts/`, the three version manifests, `Makefile`, this file, and `docs/reference/gate-authority.md` |

By hand, the two worth knowing:

```bash
pytest                          # validates nbformat + enforces the rubric on completed tutorials
python3 -m praxis.gatefloor     # fails if gate coverage dropped below the recorded floor
```

> **[CORRECTED 2026-09-03 — this file, `docs/reference/packaging.md` and
> `.github/workflows/ci.yml`'s own header each described the gate as *three* checks
> (`npm run build`, `cargo build`, `pytest tests/`). It has been more than three since
> `validate_nbgrader.py` and `praxis.gatefloor` were added, and six since the two doc
> gates landed on 2026-09-03. Three statements of one list is why it drifted; the list is
> now here and the other two point at it.]**

A tutorial is "complete" only when `nbstatus.py` reports ✅ **and**
`tests/test_notebooks.py` passes for it. Never flip a status on an unfilled notebook, and
never use placeholder URLs in Resources — they must be real links.

Gate coverage is a **ratchet**, held by the same gate: the reached figure is recorded in
[`notebooks/coverage-floor.json`](notebooks/coverage-floor.json), and
[`praxis/gatefloor.py`](praxis/gatefloor.py) re-measures the library on every run and
fails when a domain — or the library — gates fewer notebooks than it already did. It is a
floor, not a count: raising coverage never fails it. Nothing there is stored *as*
coverage; the report is always recomputed (`praxis/coverage.py`), and the floor is only
what has already been reached. Raise it with `python3 -m praxis.gatefloor --record`, which
rewrites the floor and the README claim above from one measurement so the two cannot
drift.

## Roadmap

The shipped product above is the `10`→`60` build program. The **gating backfill**
(`chief/79`–`81`, run by `chief/87`) has since shipped *and run*: the machinery merged,
six domains that had no gate at all were taken to 100%, and coverage went from 24/245 in
8 of 14 domains to the 117/245 in 14 of 14 stated at the top of this file — with the
remaining 128 deferred by a dated decision rather than forgotten. What it cost per
notebook is measured in
[`docs/explanation/gating-backfill-cost.md`](docs/explanation/gating-backfill-cost.md).

The three forward programs have since **merged** as well: **JD-driven tutorial suggestion**
(`chief/74`–`78` — ingest a job description, gap-analyze it against the library, suggest
only what's genuinely missing), **chief-powered construction** (`chief/82` — batch
construction/gating as headless Chief tasklists on local inference), and **hardening +
seed-library upkeep** (`chief/70`–`73`, `83` — signed/notarized bundles, an embedded
interpreter, storage depth, library refresh). The full reality-checked picture — including
which merged record overstates what landed, and what upkeep stays open — is
**[ROADMAP.md](ROADMAP.md)**, which is canonical for this repo's state.

> **[CORRECTED 2026-09-11 — this paragraph said the three programs were "authored as Chief
> tasklists but not yet run". Every tasklist it names is in `tasks/chief/completed/` carrying a
> `mergedToMain` (`70` → `ed96395` … `83` → `d22667d`), and `ROADMAP.md` has said so since its
> 2026-09-11 reconciliation. A README restating a roadmap's state is the two-copies-of-one-fact
> failure this file has hit twice before; the state has one home and this paragraph now points
> at it.]**

## Renaming note

The rebrand from `ai-tutor` is complete, in-repo and out: the package name, console
scripts, notebook metadata key and docs use `praxis`, and the GitHub repository itself
now lives at **`github.com/danieldekerlegand/praxis`** (the `origin` remote points
there), with the local checkout directory renamed to `praxis` to match.

Notebooks authored before the rebrand used a `metadata.ai_tutor` block; the seed library
has been migrated to `metadata.praxis`, and `nbstatus.py` still reads the old key as a
fallback so externally-authored legacy notebooks keep working.

## History

The legacy generators `generate_notebooks.py` and `enhance_notebooks.py` were removed
by the hygiene sweep — `curriculum.py` + `scaffold_notebooks.py` superseded them, nothing
imported or invoked them, and git holds them if they are ever wanted again
(`docs/explanation/dead-code-inventory.md`, A5). The original study list praxis was built
from is kept for history at `docs/archive/technologies.md` **[CORRECTED 2026-09-03 — it
was at the repo root and banner-stamped `Current`; it is neither current nor a Tier-1
root file, and 6 of its 145 hand-maintained "notebook not yet written" entries had a
notebook. The generated `docs/reference/curriculum.md` is the live catalog]**.

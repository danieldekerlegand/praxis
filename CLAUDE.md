# Praxis — notes for coding agents

Praxis constructs interactive, gated notebook tutorials for any subject. The Python core
(rubric · scaffolder · gate · launcher · seed notebooks) is the product; `src-tauri/` +
`ui/` are a shell around it. Extend that core — don't reimplement it in Rust or TS.

## Build order and the two ways a Tauri window goes blank

1. `ui/dist` is embedded at **compile** time. Always `npm run build` in `ui/` before
   `cargo build`. `src-tauri/build.rs` writes a placeholder `index.html` when `ui/dist`
   is missing, so a green `cargo build` does not prove the real UI is inside.
2. Embedding only happens with the `custom-protocol` feature (default-on in
   `src-tauri/Cargo.toml`). Without it Tauri loads `build.devUrl` (:1420) and the window
   is **blank white with no error** unless a Vite dev server is running. Use
   `cargo run --no-default-features` + `npm run dev` when you want HMR.

A window that opens with the right title proves nothing about the page. To check the page
actually ran, look for a call reaching the backend (e.g. a request in the launcher's
access log) or screenshot the window by its CGWindow id — `screencapture -l<id>` returns
only the frame for an occluded window, so raise it first (`AXRaise` via System Events).

## The library path

`launcher/app.py` owns browse/render for both UIs: `build_model()` → `/` (its own HTML)
and `/api/library` (JSON for the shell), `/render/<rel>` for a read-only notebook. Badge
logic lives in `nbstatus.py` only. `src-tauri/src/library.rs` starts that app on a free
loopback port; the webview fetches it directly, so cross-origin access is gated by
`SHELL_ORIGIN_RE` in `launcher/app.py` — extend that regex, don't widen it to `*`.

The two stylesheets `launcher/static/app.css` and `ui/src/app.css` share `:root` tokens on
purpose. Keep them in sync.

## Curricula: seed and generated

`curriculum.py` is one model for both. A user-defined subject's **modules are `Domain`s**
(`Module = Domain`), so the scaffolder, the launcher and the gate need no branch for them —
give a new consumer `Domain`/`Topic` and it works on either. Only `Domain.source` differs:
`manifest` (every topic has a notebook) · `filesystem` (scan the dir) · `subject` (topics
are enumerated, but only the scaffolded ones exist yet).

`Domain.dir` is always relative to the notebooks root — that string is the `rel` in
`/api/library` and `/render/<rel>`. Resolve it to a path with `domain_path(domain)`, never
by hand: a generated subject resolves under `subjects_dir()`, which `PRAXIS_SUBJECTS_DIR`
relocates so tests don't write into `notebooks/`.

The AI never writes files directly. `praxis/curriculum_gen.py` asks for JSON, and
`subject_from_dict()` normalizes it — lenient about what the model omits (slugs, dirs,
flags), strict about what would break the scaffolder. Extend that validation rather than
trusting a payload downstream. Generated content is gitignored (`notebooks/subjects/`).

Scaffolding is the second, separate write: `scaffold_domain()` / `scaffold_subject()` in
`scaffold_notebooks.py`, reached from `POST /api/subjects/<slug>/scaffold`. Keep it
**idempotent — an existing notebook is skipped, never rewritten** — because a curriculum
gets re-scaffolded after an author has already filled part of it. Anything generated per
notebook that depends on where the file sits (the rubric backlink, for one) must be
computed from `Domain.dir`'s depth: a seed domain is one level under `notebooks/`, a
subject's module is three.

## Construction: filling a scaffold to the rubric

`praxis/construct.py` is the third write, after "define" and "scaffold": it asks the model
for the notebook's cells as JSON, assembles them, **grades the result, and only then
writes**. The grader is `praxis/rubric.py` — the single machine-readable definition of
"complete", shared with the gate:

- `gate_failures(nb)` is exactly what `tests/test_notebooks.py` asserts (placeholders,
  the 8 sections, size, code-cell count). Both callers use it, so they cannot drift.
- `construction_failures(nb)` is that plus the three things a model will fake: the ✅
  badge from `status_from_dict()`, real `https://` URLs under Resources, and code cells
  that `compile()`. Tighten *this* one when you find a new fabrication — the seed
  library is only held to `gate_failures`, so it stays green.

Two invariants worth keeping: content that fails the grader is **never written** (the
scaffold survives, the failures come back in `ConstructionResult.failures`), and an
already-✅ notebook is **skipped, not rewritten**, unless `force=True` — same idempotence
rule as the scaffolder, and what makes a batch run resumable. A failed attempt is fed
back to the model with the grader's own sentences (`_repair_prompt`) rather than retried
blind, so those sentences are the UI's error text too: keep them specific enough to act on.

`construct_each(targets)` is the **one batch loop** — `construct_domain` and
`construct_subject` are one-liners over it, and so is the launcher. Resumability is not
implemented there; it falls out of every target going through `construct_topic`.

## Knowledge checks: the learner-side gate

`praxis/checks.py` is the **fourth write**, and the reason `construct_topic` is not the
end of the story: a notebook that passes the rubric is still ungated until the questions
that unlock the next section exist. They live *beside* the notebook as
`<slug>.checks.json` (`checks_path()`), never inside it — the answer key must not sit in
a cell the learner is reading, and the seed library gains checks without being rewritten.

Everything about it is the constructor's shape one level up, deliberately: ask for JSON,
normalize leniently (`checks_from_reply`), grade strictly (`checkset_failures`), repair
with the grader's own sentences, and **never write a set that fails**. Sections come from
`GATED_SECTIONS`, derived from `rubric.RUBRIC_SECTIONS` minus Setup/Resources, so adding
a rubric section adds a gate.

The one rule that carries the anti-fabrication weight: a `code` check's reference
`solution` is **run against its own `test`** in a subprocess before the set may be
written, so "auto-graded" can never mean "asserts nothing". That verification is the
`verify_code=True` half of `checkset_failures` — the load path (`needs_checks()`) uses
`verify_code=False` and stays cheap. `grade()` is the same code path a learner's answer
takes: `choice`/`code` auto, `short` by the model with the answer recorded verbatim on
the `CheckOutcome`.

`construct_topic(..., checks=True)` attaches a `ChecksResult` to the
`ConstructionResult`. A set the model couldn't make gradable does **not** un-write a good
notebook: `result.ok` is about the notebook, `result.checks_ok` about the gate.

## Progression: what the checks actually gate

`praxis/progress.py` is the learner's side, and it is deliberately *only* bookkeeping and
one rule: **a section unlocks when every check in every earlier section has a passing
outcome** (`section_gates()`), and the same rule one level up orders a module's topics
(`module_gates()`). It never grades — `checks.grade()` produces the `CheckOutcome`, this
records it — and it never stores an unlock. Both are re-derived from the recorded
outcomes on every request, so there is no flag anyone can set, and a check the learner
later fails genuinely re-locks what it had opened.

A topic with no `<slug>.checks.json` gates nothing. That is what keeps the 221 seed
notebooks browsable, and it means gating appears exactly where the constructor wrote
questions.

Two boundaries carry the anti-fabrication weight, both server-side:
`checks.learner_check()` is the only way a check reaches a client (`answer`, `solution`,
`test`, `expected` never cross it, and `explanation` only after grading), and a locked
section serves **no checks at all** while `POST /api/study/<rel>` answers **423** for one
the learner hasn't reached. A disabled button is not the gate.

Progress persists as one JSON file per learner under `progress_dir()`
(`PRAXIS_PROGRESS_DIR` relocates it, as `PRAXIS_SUBJECTS_DIR` does for subjects) — and
what is stored is the whole outcome, learner's answer included, not a boolean.

In the app it is one more view model, not a second source of truth: `/api/library`'s
topic rows carry `gated`/`locked`/`passed`/`checks` (folded in by `_gated()`, from the
same `module_gates()`), `GET|POST /api/study/<rel>` serve and move one topic's gate, and
`ui/src/KnowledgeChecks.tsx` renders whatever the launcher says — it holds no unlock
logic. Answering refetches the library, which is how finishing a topic unlocks the next
one in the list. Grading a `short` answer is the one path that needs a key (503),
because `choice` and `code` grade locally.

## Construction in the app

`POST /api/construct` takes `{rel}` | `{domain}` | `{subject}` and answers **202 with a
job** (`launcher/jobs.py`), because filling a curriculum is one model call per notebook.
The job is bookkeeping only — it reports `ConstructionResult`s and re-reads each badge
from `nbstatus` off the file, so it cannot claim a notebook the constructor didn't write.
One job runs at a time (409 otherwise); the key is resolved only if some target still
needs the model — a ✅ notebook whose checks are missing counts (`needs_checks()`), so
re-running a *finished and gated* curriculum needs no key, but one that is merely
constructed does.

In the UI, `useConstruction` is held **once**, at the top of `App.tsx`, and passed to
`DefineSubject` — one poller, and a run started in either view is the run the other one
shows. It adopts whatever `GET /api/construct` says is in flight when it mounts, so
reopening the window rejoins a run instead of showing a stale library.

A library `rel` is resolved by `topic_for_rel()`, not by joining paths: a generated
subject's `Domain.dir` is not where the file sits once `PRAXIS_SUBJECTS_DIR` moves it.
Same reason `launcher.app.library_path()` exists for `/render`.

## Gates

`python3 -m pytest -q tests/` (notebook core + launcher API), `npm run build` in `ui/`,
`cargo build` in `src-tauri/`. `.chief/verify.sh` runs them path-scoped. The launcher tests
skip themselves without the launch extra: `uv pip install --python .venv/bin/python -e '.[launch]'`.

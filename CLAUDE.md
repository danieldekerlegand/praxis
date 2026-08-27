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
by hand: a generated subject resolves under `subjects_dir()`, which lives on the active
storage backend, not in `notebooks/`.

The AI never writes files directly. `praxis/curriculum_gen.py` asks for JSON, and
`subject_from_dict()` normalizes it — lenient about what the model omits (slugs, dirs,
flags), strict about what would break the scaffolder. Extend that validation rather than
trusting a payload downstream. Generated content is the user's, and is written outside the
repo entirely — see **Storage** below.

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
`<slug>.checks.json` (`checks_path()`), while learner-facing graded regions carry the
standard nbgrader cell metadata. The answer key must not sit in a cell the learner is
reading; reference answers remain in the sidecar until release mechanics produce an
assignment. `migrate_checks_to_nbgrader()` is the idempotent conversion pass for seeds.

Everything about it is the constructor's shape one level up, deliberately: ask for JSON,
normalize leniently (`checks_from_reply`), grade strictly (`checkset_failures`), repair
with the grader's own sentences, and **never write a set that fails**. Sections come from
`GATED_SECTIONS`, derived from `rubric.RUBRIC_SECTIONS` minus Setup/Resources, so adding
a rubric section adds a gate.

The validation split is deliberate: `praxis/rubric.py` owns Praxis's eight sections,
placeholder/resource/badge/size/code-shape rules; `nbgrader validate` owns nbgrader
metadata well-formedness and execution of authored solution/test regions. The adapter
`praxis.checks.nbgrader_validate()` is the authoritative write gate for graded cells.
Do not add a parallel pytest implementation of nbgrader's validation rules.

The one rule that carries the anti-fabrication weight: a `code` check's reference
`solution` is **run against its own `test`** in a subprocess before the set may be
written, so "auto-graded" can never mean "asserts nothing". That verification is the
`verify_code=True` half of `checkset_failures` — the load path (`needs_checks()`) uses
`verify_code=False` and stays cheap. `grade()` is the same code path a learner's answer
takes: `choice`/`code` auto, `short` by the model with the answer recorded verbatim on
the `CheckOutcome`.

`construct_topic(..., checks=True)` attaches a `ChecksResult` to the
`ConstructionResult`. A set the model couldn't make gradable does **not** un-write a good
notebook: `result.ok` is about the notebook, `result.checks_ok` about the gate. A topic
that was skipped as already-✅ still gets its graded cells written when it carries none
yet — that resume path *is* the gating backfill, and writing only the sidecar there would
quietly reintroduce the format the nbgrader schema replaced.

`praxis/backfill.py` is that same path pointed at the library the seed notebooks are
already in. It writes no gate of its own — it **selects** (the ✅-but-ungated topics of
one domain) and hands them to `construct_each`. Two rules make an unattended run safe:
a notebook that is not yet ✅ is left for construction, never force-gated, and an
already-gated one is skipped, where gated means `checks.graded_cells(nb)` **and** a
loadable answer key — a sidecar on its own is a half-migrated gate, not a gate. That
state converges without a model call: `generate_checks` republishes the stored set's
cells rather than asking for new questions. `publish_graded_cells()` is the one write —
annotate, `nbgrader validate` a staging copy, and release only what nbgrader produced.

`backfill_library()` is the batch over all 14 seed domains, and the only thing it adds to
`backfill_domain` is the **order**: `library_targets()` interleaves the domains — `depth`
targets from each before any domain's next — so an interrupted or capped run leaves every
domain a little gated instead of three domains finished and eleven with none. Coverage
across the library is what the gate is worth, so breadth is the default (`depth=1`, a pure
round robin). Generated subjects are excluded from the seed batch on purpose; they reach
the same gate through `construct_subject`.

`praxis/coverage.py` is what makes those batches visible, and it **scans nothing**: it is a
fold over the topic rows `launcher.app.build_model()` already builds, because a second scan
would be a second definition of "gated" and the two would drift. A row counts only when
both halves are on disk — `gated` (the answer key, folded in by `module_gates()`) **and**
`graded` (the nbgrader cells, folded in by `_gated()` off `checks.graded_cells()`) — which
is `backfill.is_gated()` restated on the view model, so the batch that writes gates and the
report that counts them agree by construction. The **per-domain fraction is the primary
figure** for the same reason breadth is the batch's default; the overall one is their sum,
never a separate count. `python3 -m praxis.coverage` prints it: the seed library shipped at
24/245 in 8 of 14 domains, and the six domains that had none at all were taken to 100% by
runs of the shipped batch — 117/245 in 14 of 14 — see
`docs/explanation/gating-backfill-cost.md` for what they cost.

The **complement** of `gated` is split rather than left as one number, because "no gate"
was hiding two situations. `praxis/ungated.py` is the tracked register of decisions to
leave a notebook for later (`notebooks/ungated.json`, an entry per domain or per notebook
carrying a `reason` and a `decided` date); coverage folds it in, so every row it covers is
**deferred** and what remains is **omitted** — ungated with nothing on record. Omitted is
the number to watch, and it is 0. Two rules keep the register honest. It is **graded
against the live rows**, never against itself (`register_failures`), so an entry naming a
domain that no longer has an ungated notebook, or a `rel` overtaken by a gate, is reported
as stale rather than believed — and a corrupt register degrades toward *omitted*, never
toward deferred. And it is a **record, not a rule**: nothing in it is excluded from
`backfill_targets()`, because a register that quietly shrank the queue would turn "we
decided to wait" back into "we forgot", which is the confusion it exists to remove.

In the app it is a field, not an endpoint: `build_model()` folds the report onto
`/api/library` as `coverage` and each domain's own fraction onto its row as `covered`, so
a resumed backfill's new gates arrive on the next library refetch — no second scan, no
second poll, and `library_report()` reads that same key rather than counting again. Both
UIs render what the launcher counted (`ui/src/App.tsx`, `launcher/templates/index.html`)
and neither holds coverage logic, the same rule `KnowledgeChecks.tsx` follows for locks.

`praxis/gatefloor.py` is the **ratchet**, and it exists because a number nobody records is a
number nobody notices moving: the library sat at 24/245 for a fortnight after the machinery
to raise it had merged. It records exactly one thing — the coverage already reached, in
`notebooks/coverage-floor.json` beside `ungated.json` — and what keeps `coverage.py`'s "no
number here is ever stored" rule intact is that the recorded figure is **never read as
coverage**: coverage is always measured (`measure()`, a fold over `backfill.coverage()`, so
`is_gated()` stays the one definition and no launch extra is needed), the floor is always
loaded, and `regressions()` compares them **in one direction only**. Per domain first, for
the reason breadth is the batch's default — five gates moving from one domain to another
leaves the headline flat. A rise never fails it. A missing or corrupt floor **fails**,
because deleting the record is the one edit that would switch the check off. It also owns
the reader-facing half: `README.md` states the figure in prose, `claim()` reads it back out
of that sentence, and `record()` rewrites the floor and the sentence from one measurement —
the only supported way to raise the ratchet, so the number a reader meets and the number the
gate enforces cannot drift. `python3 -m praxis.gatefloor` runs in `.chief/verify.sh` and CI
beside `validate_nbgrader.py`; change one and change the other, as with every other check in
that pair.

`praxis/gateaudit.py` asks the question the two write-path gates cannot: `nbgrader
validate` proves a graded cell is well-formed and that its hidden tests run, and
`checkset_failures` proves the set is *gradable* — neither proves it is worth grading.
That residue is all this module looks at, and it re-implements no part of either: it
calls `checkset_failures` for the gradability half and adds four measured rules — a
`choice` whose correct option is already spelled out in its prompt, a `short` whose key
is quoted back in the question or copied out of the notebook body (`body_text()` drops
the Praxis-owned cells first, because a question is not evidence for itself), a `code`
check whose `test` still passes an empty submission or the starter stub (the shipped
`run_code_check()` subprocess pointed the other way — generation proves the reference
solution passes, the audit proves nothing else does), and two near-identical prompts in
one set. Every threshold was measured against the 24 hand-built seed gates, which is the bar
a backfilled gate has to hold: `python3 -m praxis.gateaudit` flags 0 of the gates on disk,
and a test pins that — as a floor over a growing corpus, since the backfill's job is to add
gates. Tighten a threshold only with that measurement in hand, and re-measure it against the
24 rather than against whatever a batch has since written.

Those four rules are also **the write path's**, not a report run after the fact:
`checkset_failures(doc, quality=…, notebook=…)` calls `quality_failures` /
`duplicate_failures` out of `gateaudit`, so a trivial set is rejected and never written
exactly where an ungradable one is, and the sentences become `_repair_prompt`'s feedback
and the UI's error text. `quality` follows `verify_code`, which is what keeps the two
paths honest: the cheap load path (`needs_checks()`, and generation's already-generated
skip) runs neither, so a gate written before the bar existed is skipped rather than
silently re-judged or rewritten — re-auditing those is `gateaudit`'s own pass, on
purpose. Import it **inside** the function: `gateaudit` imports `praxis.checks` at
module level, so the dependency runs one way at import time.

`praxis/regate.py` is that pass, pointed at the gates that were already on disk when the
bar landed — and it needs no marker to find them: the write path now rejects a set that
fails the tightened bar, so a gate that fails it **is** one written before the tightening,
measured rather than recorded (the same reason `progress.py` re-derives an unlock instead
of storing one). It owns no rule. `bar_failures()` is one call to
`checkset_failures(doc, verify_code=True, notebook=body_text(nb))` — `quality` left to
follow `verify_code` — so what it reports is exactly "would the write path accept this
today?", down to the sentence; `gateaudit` splits the two halves for its report, this
deliberately does not. The outcomes are `refresh.py`'s vocabulary one level down:
**HOLDS**, **FLAGGED-FOR-HUMAN** (the default — a re-audit writes nothing, the flagged
gate stays where it is, and the notebook keeps the gate it had), and **FORCE-REGENERATE**,
an explicit per-gate opt-in that hands the topic to `generate_checks(force=True)`. That
is the whole safety argument for regeneration: the shipped write path grades and
`nbgrader validate`s before it writes, so a candidate that fails the tightened bar leaves
the existing gate byte-identical rather than stripping the notebook of one. A gate that
holds is never a regeneration target even with `force=True`, so an unattended re-audit
costs no model call. `python3 -m praxis.regate` prints it; the gates on disk, every one of
them written before the bar, hold it, and a test pins that — as a floor, not a count, because
the backfill's whole job is to raise the count and a suite that fails when coverage rises
punishes the tool for working.

`praxis/authored.py` is the seam that lets the batch run with an **author** where the model
goes, and it is the reason the shipped batches could sit unrun: `backfill_domain` →
`construct_each` → `generate_checks` is a grader wrapped around one HTTP call, so with no key
configured the grading — the part that is actually the product — is unreachable too.
`generate_checks` reads exactly two things off its client (`complete()` and `config.model`),
so `AuthoredClient` serving a reply from `<slug>.checks.draft.json` beside the notebook is a
complete substitute for a provider, and `backfill_domain(domain, client=…, attempts=1)` is
the whole integration. It owns **no gating rule**: normalization, `checkset_failures` with
the subprocess run and the measured triviality rules, `publish_graded_cells` and `nbgrader
validate` all run unchanged, and a draft that fails any of them is not written while the
notebook stays byte-identical — `tests/test_authored.py` pins each refusal against a file
rather than a model. One attempt, deliberately: `_repair_prompt` handed back to a file gets
the same file. The one coupling is that a draft is found by the topic title `build_prompt`
quotes in its `<topic>` tag, and a test pins that round trip so a change to the prompt's
shape fails rather than selecting the wrong draft. Drafts are git-ignored: the accepted
`<slug>.checks.json` is the durable artifact, and a tracked draft would be a second copy of
the same questions with nothing keeping the two in sync.
`docs/explanation/gating-backfill-cost.md` is what the first measured domain cost.

## Driving the batch unattended: Chief tasklists

`praxis/tasklist.py` is a **generator, not a second batch**. Praxis already owns the loop
(`construct_each`, and `backfill_domain` in front of it); what it does not own is running
that loop with nobody in front of the app. So this module cuts the live library into
*units* — one seed domain's gate (`gate-<domain.dir>`) or one generated subject's build
(`build-<subject.slug>`) — and emits `tasks/chief/<name>.json` whose stories run the
**shipped** commands, `python3 -m praxis.backfill <dir>` and `python3 -m praxis.construct
--subject <slug>`. It constructs nothing and gates nothing; a tasklist that drove its own
construction would be a second definition of "complete" and the two would drift.

Three rules do the work. Resumability is **not written here** — it falls out of
skip-if-✅ (`construct_topic`) and skip-if-gated (`backfill.is_gated`), which is why
`iters` scales with the backlog: another iteration is another resumed pass, not a harder
story. A unit with an empty backlog is **refused** (`unit_for`), because an empty tasklist
is a Chief run that ends `EMPTY-NO-WORK` having proved the domain was already gated. And
the document is **graded before it is written**, the constructor's rule one level up:
`tasklist_failures()` is the machine-readable half of chief's `docs/reference/tasklist-schema.md`
(branch is `chief/<name>`, a category `scripts/check-tasklist-categories.mjs` accepts, every
story `passes: false`, no `mergedToMain`), and `write_tasklist` writes nothing that fails
it — nor over a tasklist that is already active or retired, whose `passes` flags are
chief's bookkeeping and not this module's to reset.

`touches` is the one scheduler field carrying a decision: a unit declares the notebook
tree it writes (`notebooks/<dir>`, `subjects/<slug>`), so fourteen domain gates run in
parallel while two tasklists on the *same* domain never co-schedule. The one asymmetry
worth knowing: a backfill's notebooks are in the branch, but a generated subject is the
user's data and is written **outside the repo** under `storage`'s root, so a subject
tasklist's evidence is the recorded badge/gate counts, not a diff.

`python3 -m praxis.backfill [--list] [DIR…]` is the entry point those tasklists name —
`--list` prints the selection with no model call and no key, which is what a generated
tasklist's `warmup` (`python3 -m praxis.tasklist show <name>`) is for.

`praxis/headless.py` is the other half — it **starts** one of those tasklists and reads its
result back, and it consumes two chief contracts **by reference**, the way `llm.py` consumes
agora's: a documented CLI shape and two environment variables, never an import or a path
into another checkout. `docs/reference/chief-powered-construction.md` is the prose contract.

`chief run --headless` adds machine-readable lines to the same engine — `chief: run-id=`
before the loop, `chief: outcome=` / `exit=` / `summary={…}` after it, and an exit code that
names the outcome. **Only those are read.** `records()` keeps `chief: <key>=<value>` lines
and drops every other byte on the stream, so the human summary block sharing it cannot be
scraped by accident; `parse_run()` takes the outcome from the summary JSON, then the
`outcome=` line, then the exit table — three machine-readable sources and no fourth — and
**raises** on a stream with no run-id rather than inventing one (a test prints a human block
saying "All tasklists merged successfully" next to a summary saying `verify-failed`, and
pins that the summary wins). A `chief: exit=` that disagrees with the process's own status
is refused for the same reason.

`chief run --preset local` is the routing switch, and `LocalPreset` is its two required
variables (`CHIEF_LOCAL_ENDPOINT`, `CHIEF_LOCAL_MODEL`) and nothing else — no `--provider`
or `--model`, which chief refuses next to the preset rather than guessing who is paying, and
no default host. `LocalPreset.failures()` is chief's own refusal made one process earlier:
an unconfigured preset stops the batch **before it spawns** instead of quietly billing a
paid provider for a run that was asked to be free. The tradeoff is deliberate and belongs
here rather than in the app: a local model writes worse code, but every artifact still goes
through `construction_failures` / `checkset_failures(verify_code=True)` / `nbgrader
validate` before it lands, so a weaker model costs **iterations, not correctness**.

Resumability is again not implemented — `unfinished(run)` is just the rows chief reported as
unfinished, and re-running them is safe because of skip-if-✅ and skip-if-gated one and two
levels down. The CLI exits with **chief's own exit code**: `python3 -m praxis.headless` is
the plan (preset, units, exact argv, no spawn), `… run [names] [--jd ID] [-p N]` drives it.

## Progression: what the checks actually gate

`praxis/progress.py` is the learner's side, and it is deliberately *only* bookkeeping and
one rule: **a section unlocks when every check in every earlier section has a passing
outcome** (`section_gates()`), and the same rule one level up orders a module's topics
(`module_gates()`). It never grades — `checks.grade()` produces the `CheckOutcome`, this
records it — and it never stores an unlock. Both are re-derived from the recorded
outcomes on every request, so there is no flag anyone can set, and a check the learner
later fails genuinely re-locks what it had opened.

A topic with no `<slug>.checks.json` gates nothing. That is what keeps the 245 seed
notebooks browsable, and it means gating appears exactly where the constructor wrote
questions.

Two boundaries carry the anti-fabrication weight, both server-side:
`checks.learner_check()` is the only way a check reaches a client (`answer`, `solution`,
`test`, `expected` never cross it, and `explanation` only after grading), and a locked
section serves **no checks at all** while `POST /api/study/<rel>` answers **423** for one
the learner hasn't reached. A disabled button is not the gate.

Since JupyterLite became the runtime the browser is explicitly **untrusted**, and
`docs/reference/gate-authority.md` is the one place that says which process holds the key
(`tests/test_gate_authority.py` enforces it — the doc is in the python path predicate of
both `.chief/verify.sh` and CI for that reason). Two rules were added there and both are
one-liners you must not route around. `checks.learner_answer()` is `learner_check()`'s
**inbound twin**: a submission is read for `check_id` and `answer` and nothing else, and
one carrying a verdict (`passed`, `outcome`, `graded_by`, `locked`, …) is refused **400**
rather than ignored — a client that sends a verdict believes it grades. And
`lite.browser_notebook()` is the one notebook filter for **both** untrusted surfaces: the
JupyterLite site *and* `/render/<rel>`, which is HTML in a browser with devtools. It is
stricter than `checks.graded_cells()` on purpose — nbgrader's companion `-tests` cell has
no praxis namespace and its assertions are the answer. Grading itself never moves: the
Pyodide kernel is a scratchpad, `run_code_check()` runs the submission in a subprocess of
the interpreter holding the key, so a `code` check is gradable exactly when the core is
running, which is exactly when there is a gate at all.

Progress persists as one JSON file per learner under `progress_dir()` — and what is
stored is the whole outcome, learner's answer included, not a boolean.

In the app it is one more view model, not a second source of truth: `/api/library`'s
topic rows carry `gated`/`locked`/`passed`/`checks` (folded in by `_gated()`, from the
same `module_gates()`), `GET|POST /api/study/<rel>` serve and move one topic's gate, and
`ui/src/KnowledgeChecks.tsx` renders whatever the launcher says — it holds no unlock
logic. Answering refetches the library, which is how finishing a topic unlocks the next
one in the list. Grading a `short` answer is the one path that needs a key (503),
because `choice` and `code` grade locally.

## Model access: BYO-key, with agora as one opt-in branch

`praxis/llm.py` is the only module that talks to a model, and it is one client with two
branches, not two clients. `AGORA_BASE_URL` unset is the **direct** BYO-key path
(anthropic `messages`, openai/local `chat`); set, every call goes to agora's
provider-router instead. Everything the router adds hangs off
`LLMConfig.routed_via_agora` — hints out (`AGORA_ROUTE` / `AGORA_FALLBACK_MODELS`, sent
as `x-agora-*` **headers** so a route can never become a body key a provider rejects),
what served the call back (`LLMClient.last_route`, a best-effort read of the reply's
headers then its body), and the router's own error sentence in place of the provider's.

Two rules keep it opt-in, and `tests/test_llm.py` pins both:

- the direct branch's bytes are **frozen** — endpoint, headers, payload, error strings.
  `DIRECT_WIRE` asserts the whole request per provider, so anything new must sit behind
  `if self.config.routed_via_agora`. `AGORA_*` left in a shell without `AGORA_BASE_URL`
  resolves but changes nothing.
- agora is a URL in an env var, never an import or a manifest entry. Its wire vocabulary
  is consumed **by reference** — one block of `x-agora-*` constants at the top of the
  module, all of it a hint going out and a best effort coming back, so a router that
  ignores or omits every bit of it still behaves like the plain base-URL swap.

## Storage: whose data, and on which disk

`praxis/storage.py` is the only module that knows where the user's data lives. The four
writes above (subject · scaffold · construct · checks) plus progress and an imported job
description all land under **one root**, laid out as `<root>/subjects/<slug>/…`,
`<root>/progress/<learner>.json` and `<root>/jd/<id>.json`
(`docs/reference/storage.md` is the contract). The seed `notebooks/` are not user data — they ship
with the app and are never written to.

Nothing else resolves a storage path. `curriculum.subjects_dir()` and
`progress.progress_dir()` are one-line delegates, which is why every existing caller
followed the root the day it moved. Adding a backend is a resolver in `_RESOLVERS` (plus
an availability check in `_AVAILABLE` when it isn't a plain path) — **never** a new path
computation in a caller. Four ship: `app`, `drive` (the picked folder, verbatim), `cloud`
and `webdav`. The last goes in through the public `register_backend()` seam rather than
into the tables, so what a fifth would do is what the fourth already does — keep it there.

`_drive_available()` is stricter than `_local_available()` on purpose, and the comment
there is the reason: an unplugged disk leaves `/Volumes` behind, so walking up to the
first *existing* ancestor would recreate the drive's folder on the internal disk and let
the user fill a decoy. The **immediate** parent must be there. The same failure is why
`launcher/app.py` has a middleware refusing every non-GET with 503 while
`Backend.writable()` is false — one place, so no endpoint can forget, and `/api/storage`
is exempt because it is the fix. `writable()` is the local, cheap half of `available()`;
they differ only for `cloud`, which stays writable offline.

`cloud` and `webdav` are each a **local mirror plus a sync** (`praxis/cloud.py` over
`praxis/s3.py`, ~250 lines of urllib+hmac rather than boto3; `praxis/share.py` over
`praxis/webdav.py`, urllib again), because every writer here writes with `Path`.
The merge rule is content-based: `.praxis-sync.json` records the digest both sides last
agreed on, so the side that *changed* wins and mtimes only break a true conflict — a
timestamp rule alone loses an edit made in the same second as the previous sync. A sync
never deletes. `tests/mocks3.py` and `tests/mockdav.py` serve the real protocols on a loopback
port, so the sync tests sign and send what AWS or Nextcloud would receive; a round trip is
proved by wiping the mirror and reading the work back in a second process. Each fake is
awkward where the real thing is — `mockdav` refuses `Depth: infinity`, 409s a `PUT` into a
collection that doesn't exist, and serves an `ETag` that is deliberately *not* the body's
digest, so nothing can quietly assume S3's.

`storage.FIELDS` / `BLURBS` are the settings form's single source of truth —
`ui/src/StorageSettings.tsx` renders whatever `GET /api/storage` describes and knows no
backend by name. A stored secret is reported as `set: true`, never by value, so a blank
secret field means "keep the stored one" (`merge_options`).

The active backend is `storage.json` in `app_dir()`, deliberately *outside* the root it
selects: an unplugged drive must still leave the app able to say which drive it wants. A
config that is missing or corrupt reads as app storage, so it can cost a user their
selection but never their data. `select_backend()` resolves, checks and creates before it
stores, and `available()` is re-checked per request — a mount can vanish between two calls.

`app_dir()` is the shell's Tauri `app_data_dir()`, passed down as `PRAXIS_APP_DIR`
(`Launcher::use_app_data`); with no env, Python computes the same per-OS path from the
same bundle identifier, so `praxis-launch` by hand sees what the app wrote. Keep
`storage.APP_ID` equal to `tauri.conf.json`'s `identifier` — a test asserts it.
`tests/conftest.py` points `PRAXIS_APP_DIR` at a tmp dir for **every** test; a test that
writes user data must never rely on the real one.

## Job descriptions: the one document the user brings

`praxis/jd.py` is the front of a different funnel — everything else starts from a subject
the user *types*; this starts from a posting they already have. It is a parser and a
normalizer, nothing more: pasted text or an uploaded `.txt`/`.md`/`.pdf`/`.docx` becomes
**one canonical plain text**, and every later band reads that one field, `doc["text"]`,
whatever the file it arrived as. Three properties carry the weight:

- **No model.** `praxis/llm.py` is not imported here, so importing a JD works with no key
  configured — BYO-key starts one band later, at extraction. A test asserts a restart
  reading a JD back never loads `praxis.llm`.
- **No parser for a format that doesn't need one.** `.txt`/`.md` are a decode; `zipfile`
  and `zlib` are imported *inside* the `.docx` and `.pdf` readers. All four are stdlib,
  the same call `praxis/s3.py` makes against boto3.
- **Nothing that failed to parse is persisted** — an unsupported extension, bytes that are
  not text (CP1252 decodes anything, so binary is caught *before* the fallback, not by it)
  and a scan with no extractable text are each a `JDError` naming the file and what to do
  instead. Same rule as the constructor's: the failure comes back, no file is written.

The id is the title's slug plus a digest of the normalized text, so re-importing the same
posting rewrites one document rather than piling up copies, and an edited one is new.
`tests/fixtures/jd/` holds the same posting as four real files (`textutil`, `cupsfilter`,
`sips` made them) — `.txt`, `.pdf` and `.docx` must normalize to the *same string and the
same id*, which is the strongest available statement about a normalizer.

In the app it is two writes onto one core call: `POST /api/jd` takes `{text, title}` and
`POST /api/jd/upload?filename=` takes the file's **raw bytes as the body** — not
multipart, which is a `fetch(url, {body: file})` in `ui/src/jd.ts` and saves the launcher
a `python-multipart` dependency for a form with one field. Every `JDError` is a **400**
carrying `jd`'s own sentence, so the UI's error text is the module's; the writable() 503
middleware covers both like any other non-GET. `ui/src/ImportJD.tsx` shows the import back
by re-reading `GET /api/jd/<id>` rather than the response body, so the confirmation is
what landed on the backend and not an echo — the same reason the construction job re-reads
each badge off the file.

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
`cargo build` in `src-tauri/`. `.chief/verify.sh` runs them path-scoped, plus
`scripts/validate_nbgrader.py notebooks` — the authoritative graded-cell gate — and
`python3 -m praxis.gatefloor`, the coverage ratchet (a drop below `notebooks/coverage-floor.json`,
or a README figure that disagrees with it, fails the merge; a rise never does). The launcher tests
skip themselves without the launch extra: `uv pip install --python .venv/bin/python -e '.[launch]'`.

`nbgrader` is a pinned **core** dependency, not an extra, so an environment without it does not
skip the graded-cell gate — it fails it. `verify.sh` probes for it alongside pytest/nbformat and
repairs a `.venv` predating the pin with the same editable install CI runs, because
`praxis.checks` resolves nbgrader's console script beside the *running* interpreter: the
interpreter that runs the tests must be the one that has it.

`.github/workflows/ci.yml` is the same three checks on every PR to `main`, with the same
path predicates — change one and change the other. Its Rust job builds the frontend first
for the reason in **Build order** above.

## Bundling

`docs/reference/packaging.md` is the contract. The Tauri CLI is a dev dependency of `ui/`, but it
locates `src-tauri/` by walking up from the **working directory** — so a bundle is built
from the repo root (`npm --prefix ui exec -- tauri build`), never from inside `ui/`, where
it silently finds no app. `tauri build` runs `beforeBuildCommand` itself, so it cannot
embed a stale `ui/dist`.

`scripts/bundle-macos.sh` is that command plus the signing decision: it reads the Apple
credentials `tauri build` already looks for **from the environment only** (never the
repo), refuses a half-configured release before the build, and otherwise falls through to
the unsigned bundle. `--check` reports the plan without building, which is what
`tests/test_packaging.py` asserts on. `tauri.conf.json` carries `bundle.macOS`'s
hardened-runtime flag and deliberately **no** `signingIdentity`.

The version is declared in **three** manifests that nothing derives from each other —
`src-tauri/tauri.conf.json`, `pyproject.toml`, `ui/package.json` — so a bump edits all
three in one commit. `scripts/check-versions.py` is the only check: the release script
runs it before building (exit 2 on a mismatch) and `tests/test_packaging.py` pins it, so
it rides CI's existing python job. That is why the python path predicate in **both**
`.github/workflows/ci.yml` and `.chief/verify.sh` scopes those three files and `scripts/`
— a lone version bump must still reach the gate.

A bundle can carry the Python side or discover it. `scripts/embed-python.sh` stages
`src-tauri/resources/praxis-runtime/{python,core}` — a relocatable CPython with the launch
extra beside a copy of the core — and `tauri.embedded.conf.json` is the **overlay** config
(`tauri build --config …`) that copies it in; the payload is untracked, so naming it in
`tauri.conf.json` would fail every build that hasn't staged one. `library.rs` prefers that
runtime and otherwise reads exactly as it did before it existed: `PRAXIS_ROOT` then the
walk-up from the binary and the cwd for the core, `PRAXIS_PYTHON` then `.venv` then
`python3` for the interpreter (`PRAXIS_NO_EMBED=1` is the way back). So an embedded `.app`
runs anywhere, an unembedded one still wants a checkout with the launch extra beside it and
says so through `LauncherStatus::failed` rather than failing silently.

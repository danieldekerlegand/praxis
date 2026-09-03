# Dead-code inventory

The measured candidate list for the hygiene sweep, produced **before** anything was removed.
Every candidate below names the search that found it, so the list can be re-run rather than
believed. A candidate list without its method is unreviewable.

Measured on `chief/900-dead-code-paydown` at `fb7ade9`, against 30,028 tracked lines of
`.py`/`.ts`/`.tsx`/`.rs` outside `notebooks/`.

## The method, and its scope

Three passes, in this order.

**1. Definition-level reachability (Python).** Parse every tracked `.py` file outside
`notebooks/` with `ast`, take every module-level `def`/`class`/`UPPER_CASE` assignment, and count
word-boundary occurrences of its name in *every* tracked text file — `.py .md .json .ts .tsx .rs
.sh .mjs .html .toml .yml .yaml .css` — plus occurrences inside its own defining file. A symbol is
a candidate only when **both** counts are zero: nothing outside references it and nothing inside
does either. Counting self-references is what keeps private helpers (`_topic_from_dict`,
`_module_dir`, `_domain_for`, …) off the list — they have no external caller by construction and
would otherwise drown the signal.

The corpus is deliberately wider than code. A name is kept alive by a doc that documents it, a
tasklist that names it, a shell script that invokes it, or a CI workflow that runs it, and this
portfolio has been bitten by exactly the narrower search.

**2. Whole-file reachability.** For each top-level script and subsystem, search every tracked
file — `notebooks/` included — for its filename and for `import <module>` / `from <module>`.

**3. Duplication.** Normalize every Python line (strip indentation), hash every 8-line window of
non-blank non-comment lines, and report windows whose hash appears in more than one file. Then
read each hit: an intentionally-independent restatement is not a duplicate (see Class C).

The equivalents for the other two languages found nothing removable:

- **TypeScript** (`ui/src/*.ts*`): no export has zero references including its own module. The 22
  exports never imported by another module are all types and helpers used inside their own file;
  the redundant `export` keyword is not dead code and stripping it is churn.
- **Rust** (`src-tauri/src/*.rs`): the only zero-reference items are the twelve `#[test]`
  functions, and `cargo build` emits no `dead_code` warning.

Reproduce the whole sweep from the repo root. The scope of every search below is
**`git ls-files`** — every tracked file, seed notebooks included — unless stated otherwise:

```sh
git ls-files | xargs grep -n '\b<name>\b'
```

---

## Class A — genuinely dead

Nothing references these, in code, docs, tests, scripts, CI or tasklists.

### A1. `curriculum.all_manifest_topics()` — `curriculum.py:399` (2 lines)

```sh
$ git ls-files | xargs grep -n '\ball_manifest_topics\b'
curriculum.py:399:def all_manifest_topics() -> list[tuple[Domain, Topic]]:
```

The definition is the only occurrence in the tree. Every consumer that wants this pair iterates
`DOMAINS` and `domain.topics` itself (`praxis/backfill.py`, `praxis/coverage.py`,
`scaffold_notebooks.py`), which is also the only form that works for a generated subject — this
helper folds over the **seed manifest only**, so it is not the shape the rest of the code needs.

### A2. `praxis.checks.NBGRADER_METADATA_KEYS` — `praxis/checks.py:95` (4 lines)

```sh
$ git ls-files | xargs grep -n '\bNBGRADER_METADATA_KEYS\b'
praxis/checks.py:95:NBGRADER_METADATA_KEYS = (
```

Its sibling one line up, `NBGRADER_SCHEMA_VERSION`, has three callers. This one has none: the
three writers that build nbgrader metadata (`praxis/checks.py:340`, `:357`, `:372`) spell the keys
out as dict literals. So the constant is not the source of truth it reads as — it is a **second,
unenforced statement** of the same schema, and the kind that drifts silently. Removing it leaves
one statement of the key set (the literals nbgrader actually validates); keeping it would need a
caller, which is a change, not a cleanup.

### A3. `praxis.jd.delete_jd()` — `praxis/jd.py:153` (7 lines)

```sh
$ git ls-files | xargs grep -n '\bdelete_jd\b'
praxis/jd.py:153:def delete_jd(jd_id: str) -> bool:
```

No caller, no test, and no route: `launcher/app.py` registers `GET /api/jd`, `GET
/api/jd/{jd_id}`, `POST /api/jd` and `POST /api/jd/upload` and no `DELETE`. Note the id rule in
`praxis/jd.py` — the id is the title slug plus a digest of the normalized text — which means a
re-import *rewrites* one document rather than accumulating copies. That is why nothing ever needed
a delete.

### A4. `praxis.s3.walk_files()` — `praxis/s3.py:295` (4 lines, plus a stranded import)

```sh
$ git ls-files | xargs grep -n '\bwalk_files\b'
praxis/s3.py:295:def walk_files(root) -> Iterator:  # pragma: no cover - trivial, exercised via cloud.sync
```

**The comment is false**, and that is the finding. `cloud.sync` does not call it: `praxis/cloud.py`
walks the mirror in `_local_files` at `praxis/cloud.py:140` with its own `root.rglob("*")`, as does
`praxis/share.py:140`. So the tree holds three implementations of "every regular file under root",
one of which is unreachable and carries a `pragma: no cover` asserting the opposite. A
`no cover` pragma that names a caller that does not exist is worse than no pragma: it tells the
next reader the coverage gap was checked.

`from typing import Iterator` at `praxis/s3.py:33` is used by this function and nothing else
(`grep -n 'Iterator' praxis/s3.py` → two lines, the import and line 295), so it goes with it.

### A5. The legacy generators — `generate_notebooks.py` (691) + `enhance_notebooks.py` (205)

```sh
$ git ls-files | xargs grep -n 'enhance_notebooks\|generate_notebooks'
README.md:573:The legacy generators (`generate_notebooks.py`, `enhance_notebooks.py`,
scaffold_notebooks.py:24:Supersedes generate_notebooks.py / enhance_notebooks.py (kept as legacy).
tasks/chief/completed/86-adopt-minio-nbformat-and-delete-legacy.json:5:  …
tasks/chief/completed/86-adopt-minio-nbformat-and-delete-legacy.json:38:  …
```

Four hits, none of them a caller: two prose lines saying the files are superseded, and two lines
of a **completed tasklist that said to delete them**. Neither file is imported by anything
(`grep -n 'import enhance_notebooks\|import generate_notebooks\|from enhance_notebooks\|from
generate_notebooks'` → no hits), neither is named by `Makefile`, `.chief/verify.sh`,
`.github/workflows/ci.yml` or `pyproject.toml`'s `[project.scripts]`, and neither has a test.

The second-order check matters more than the first: re-running pass 1 with both files removed from
the corpus produces **the same four Class-A symbols** and no new ones, so nothing in `curriculum.py`
or `praxis/` is kept alive only by them.

This is also the sweep's clearest evidence that a cleanup needs a gate. `chief/86` merged at
`aa944fa` with the story *"Replace the hand-rolled S3 client and delete the dead generators"*
marked `passes: true`; both files are still here, and its `notes` field records the story's own
premise rather than an observation of the deletion.

### A6. `sync_curriculum.py` (141 lines)

```sh
$ git ls-files | xargs grep -n 'sync_curriculum'
sync_curriculum.py:11:Run:  python sync_curriculum.py [--dry-run]
```

Its own usage line is the only occurrence in the tree. Not in `Makefile` (which wires
`curriculum`, `define`, `scaffold`, `construct`, `docs`, `tasklists` and `ralph`), not in
`README.md`, not in CI, no test. Its job — prune `notebooks/<dir>/` and `ralph/<dir>/tasks.json`
for domains dropped from the manifest — is half aimed at the subsystem in A7, and the other half
is a manual `git rm`.

### A7. The Ralph subsystem — `ralph/` + `.ralphy/` (24 files, 4,330 lines)

```sh
$ git ls-files ralph .ralphy | wc -l
24
$ git ls-files | xargs grep -n 'ralphy'      # callers, outside ralph/ itself
curriculum.py:20    (a comment)
README.md:345       (prose + a link to the external tool)
ROADMAP.md:282      (prose: "historical, superseded")
```

`ralph/run.sh` shells out to `ralphy` — a **third-party binary that must be on `PATH`**
(`ralph/run.sh:37` exits 1 if it is not) — to drive an agent that fills notebooks to
`docs/explanation/notebook-rubric.md`. That is the behaviour `praxis/construct.py` owns today,
graded by `praxis/rubric.py` before it writes; `ralph/generate_tasklists.py` is the behaviour
`praxis/tasklist.py` owns, and `ralph/*/tasks.json` (3,961 lines) is a frozen snapshot of a
backlog that `praxis/backfill.py` now recomputes from the live library.

The repo says so itself, at `ROADMAP.md:282`:

> Earlier offline notebook-filling runs used Ralph/ralphy — `ralph/`, `.ralphy/` — and are
> historical, superseded by the in-app construction agent from band 30.

So this is a **duplicated implementation of one behaviour** whose second copy the repo has already
declared historical — the Class-B failure mode, at 14% of the non-notebook tree. It is reachable
(`make ralph`, `make tasklists`) but only with an external tool installed, and running it would
drive a *different* construction path than the one every gate in this repo checks.

Stranded by its removal, and therefore in scope for the same commit: `Makefile`'s `ralph` and
`tasklists` targets, `README.md:305`/`:345`–`:353`, `README.md:124`, `curriculum.py:20`,
`generate_docs.py:82`, `docs/explanation/gap-analysis.md:9`, and the `ralph/` half of A6.

---

## Class B — duplicated implementations

Two implementations of one behaviour is the failure mode that costs most later, because they
drift. Recorded here whether or not this sweep removes them.

### B1. Three copies of "every regular file under root"

`praxis/s3.py:295` (dead — A4), `praxis/cloud.py:140` and `praxis/share.py:140`. The two live
copies are byte-identical including their docstring:

```python
def _local_files(root: Path) -> dict[str, Path]:
    """Relative posix path -> file, for every file in the mirror but the index itself."""
```

### B2. `SyncResult` in `praxis/cloud.py:66` and `praxis/share.py:62`

Identical dataclass, identical `to_dict()`. Found by pass 3 as an 8-line exact window.

### B3. The Ralph construction path vs `praxis/construct.py` + `praxis/tasklist.py`

See A7. This is B's most expensive instance: not two functions but two *pipelines* for filling a
notebook to the rubric, only one of which is graded by `praxis/rubric.py` and gated by
`.chief/verify.sh`.

### B4. `make bundle` vs `scripts/bundle-macos.sh`

Both invoke `npm --prefix ui exec -- tauri build --config src-tauri/tauri.lite.conf.json`
(`Makefile:103`, `scripts/bundle-macos.sh:136,177`). Not a duplicate to collapse: the script adds
the signing decision and the version check, and `docs/reference/packaging.md` is its contract.
Recorded so the next sweep does not re-open it.

---

## Class C — looks dead, is not

The record that stops the next sweep re-litigating these. Everything here was a candidate at some
point in the three passes and survived on evidence.

| Candidate | Why it survives |
| --- | --- |
| Every module in `praxis/` | A naive `praxis[./]<mod>` grep reports `praxis/suggestion_review.py` as unreferenced. It has **six** callers — `launcher/app.py:745,755,759,804,806,807` — reached through `from praxis import gap, jd_extract, suggest, suggestion_review`. The grep, not the module, was wrong. All 30 modules have callers. |
| `praxis/promote.py`, `praxis/audit.py`, `praxis/refresh.py`, `praxis/regate.py` | Repo-maintenance CLIs with no in-app caller, each **exercised by a test** (`tests/test_promote.py`, `tests/test_audit.py`, `tests/test_refresh.py`, `tests/test_regate.py`) and each documented (`docs/explanation/domain-addition-policy.md`, `docs/explanation/seed-refresh-policy.md`). Code a test exercises is not dead. |
| `scripts/check-tasklist-categories.mjs` | Never executed by `.chief/verify.sh` or CI, which is what made it a candidate. `tests/test_tasklist.py:224` **reads its source** to extract the category vocabulary `praxis/tasklist.py` must emit, so deleting it breaks the gate that keeps the two in step. |
| `PRAXIS_SUGGESTIONS_DIR` (`praxis/storage.py:659`) | The only leaf override with no row in `docs/reference/storage.md` and no test, unlike `PRAXIS_JD_DIR` / `PRAXIS_PROGRESS_DIR` / `PRAXIS_SUBJECTS_DIR`. It is live code on the storage resolver path; the gap is a **documentation** gap, and belongs to the sweep that runs after this one. |
| `RUBRIC_SECTIONS` restated at `tests/test_scaffold.py:41` | Byte-identical to `praxis/rubric.py:47` and reported by pass 3. Deliberate: a test that imports the constant it is pinning asserts nothing. This is an independent restatement, not a duplicate. |
| The 22 `ui/src` exports never imported elsewhere | `startConstruction`, `fetchJob`, `fetchRunning` and 19 types, all used inside their own module (`useConstruction` calls the first three). Only the `export` keyword is redundant, and `tsc --noEmit` in `npm run build` would catch a genuinely unused local. |
| The 12 zero-reference items in `src-tauri/src` | All `#[test]` functions. |
| `praxis/authored.py` and its git-ignored `*.checks.draft.json` | Deliberately unexercised in a normal run: it is the seam that substitutes an author for the model, so the batch is runnable with no key. `tests/test_authored.py` pins each of its refusals against a file. |
| The refusal paths — `storage.writable()`'s 503 middleware, `checks.learner_answer()`'s 400, `lite.browser_notebook()`'s filter, `LocalPreset.failures()` | Unreached on the happy path **by design**; each is a stated contract with a test, and `docs/reference/gate-authority.md` is in the python path predicate of both `.chief/verify.sh` and CI precisely so a claim edited out of it fails the gate. |
| Every declared dependency | `nbformat` (`scaffold_notebooks.py:35`), `nbgrader` (`praxis/checks.py`, `scripts/validate_nbgrader.py`), `fastapi`/`jinja2` (`launcher/app.py:370–374,419`), `nbconvert` (`launcher/app.py:900`), `uvicorn` (`launcher/app.py:924`), `jupyterlab` (`launcher/app.py:934`, `python -m jupyterlab`), `pytest`, `httpx` (fastapi's `TestClient`). None unused. |
| Every launcher route | All 18 routes in `launcher/app.py` have at least one client in `ui/`, `launcher/templates/index.html`, `src-tauri/` or `tests/`. |
| Commented-out code | None. The regex for commented-out `def`/`class`/`return`/`import`/`if`/`for`/`print` over every tracked `.py`/`.ts`/`.tsx`/`.rs` outside `notebooks/` returns no hits, as does a `TODO|FIXME|XXX|DEPRECAT` sweep once the rubric's own placeholder vocabulary is excluded. |

---

## Class D — unused imports

Mechanical, found by pass 1 extended to import statements. `from __future__ import annotations`
is excluded (it has no name to reference).

| File | Import | Search |
| --- | --- | --- |
| `curriculum.py:40` | `os` | `grep -n '\bos\b' curriculum.py` → the import line only |
| `curriculum.py:43` | `field` (from `dataclasses`) | `grep -n '\bfield\b' curriculum.py` → the import line only |
| `generate_docs.py:10` | `Path` | `grep -n '\bPath\b' generate_docs.py` → the import line only |
| `praxis/library_index.py:47` | `Counter` | `grep -n '\bCounter\b' praxis/library_index.py` → the import line only |
| `praxis/s3.py:33` | `Iterator` | used only by A4 |
| `scaffold_notebooks.py:29` | `json` | `grep -n '\bjson\b' scaffold_notebooks.py` → the import line only |
| `tests/test_refresh.py:1` | `json` | `grep -n '\bjson\b' tests/test_refresh.py` → the import line only |
| `tests/test_tasklist.py:44` | `CURRICULUM` | Carries `# noqa: F401`, which covers the `domain`/`subjects_root` fixtures imported beside it; `CURRICULUM` itself is unreferenced in that file |
| `generate_notebooks.py:9` | `List` | Moot — the file is A5 |

---

## What this sweep is for

Deletion is irreversible in effect even when git remembers, because nobody re-reads a deleted
file. The Class-C table above is worth more than the Class-A list: it is the record of what was
checked and survived, so the next sweep starts from evidence instead of from suspicion.

---

## What the sweep removed, in four steps

Recorded after the fact, so the list above stays the *pre-removal* measurement it claims to
be. Four commits, one subsystem each, because a single commit deleting thousands of lines
across unrelated subsystems cannot be reviewed and cannot be partially reverted.

| Step | Commit | Removed | Gate |
| --- | --- | --- | --- |
| 1 | `0051526` | A1–A4 (the four symbols) + Class D (8 imports) | `pytest -q tests/` 1205 passed, 1 skipped |
| 2 | `b8858f5` | A5 — `generate_notebooks.py` + `enhance_notebooks.py`, 896 lines | 1205 passed, 1 skipped |
| 3 | `58cecd3` | A6 — `sync_curriculum.py`, 141 lines | 1205 passed, 1 skipped |
| 4 | `942ed91` | A7 / B3 — `ralph/` + `.ralphy/`, 24 files, 4,330 lines | 1205 passed, 1 skipped |

27 files gone, 545 tracked where there were 571; 5,455 deletions against 35 insertions
outside `.chief/`. **The suite count did not move at any step, and no test was deleted,
skipped or adjusted** — which is the sweep's own bar: a removal that needs a test edited to
stay green is a removal of something live.

Re-running pass 1 over the reduced tree returns **0 candidates** (excluding `tests/`, whose
`test_*` functions are referenced by the runner rather than by a caller). The four are gone
and nothing new was orphaned by their going.

### What a removal stranded, and was fixed in the same commit

A reference to deleted code is not a docs defect for the next sweep to find — it is part of
the removal. Step 4 carried the most: `Makefile`'s `ralph`/`tasklists` targets and their
`.PHONY` entries · `README.md`'s `ralph/` table row, the `generate_tasklists.py` line in the
seed-curriculum recipe, and the ralphy block (repointed at `praxis/tasklist.py` +
`praxis/headless.py`, the shipped unattended path) · `curriculum.py`'s "Drives:" list ·
`generate_docs.py`'s three prose strings **and** the matching lines of its output,
`docs/explanation/gap-analysis.md` · `ROADMAP.md:282` · and the "Ralph" docstrings in
`nbstatus.py`, `tests/test_notebooks.py`, `pyproject.toml` and
`docs/explanation/notebook-rubric.md`. Step 2 carried `README.md`'s History paragraph and
`scaffold_notebooks.py`'s "Supersedes …" line.

`tasks/chief/completed/86-adopt-minio-nbformat-and-delete-legacy.json` was **not** edited.
Its story claimed the A5 deletion and did not perform it; that is the historical record and
rewriting it would erase the evidence for why this tasklist exists.

## What looked dead and was NOT removed

The Class C table above is the pre-removal half of this record; these are the decisions the
removal itself produced. This section is worth more than the deletions: it is what stops the
next sweep re-litigating the same files.

| Not removed | Why it survived |
| --- | --- |
| **B1 — three copies of "every regular file under root"** | One copy (`s3.walk_files`) was dead and went in step 1. The two survivors, `praxis/cloud.py:140` and `praxis/share.py:140`, are byte-identical, but collapsing them means one of the two sync backends importing the other or a new shared module — a **refactor with a behaviour risk**, not a removal. Two live callers, two test suites, no dead code. Left deliberately; it is a design question for whoever adds the fifth backend through `register_backend()`. |
| **B2 — `SyncResult` in `cloud.py:66` and `share.py:62`** | Same argument as B1, same two files. Identical dataclass and `to_dict()`, both live. Collapsing it couples the S3 backend to the WebDAV one for eight lines. |
| **B4 — `make bundle` vs `scripts/bundle-macos.sh`** | Not a duplicate to collapse: the script adds the signing decision and the version check, and `docs/reference/packaging.md` is its contract. Re-recorded so the next sweep does not re-open it. |
| **`technologies.md`** | Named only by `README.md`'s History paragraph, which step 2 rewrote. It is a **document**, not code, and the tasklist's scope is code — deciding whether a history file earns its place is the docs sweep's call, not this one's. |
| **`praxis/authored.py`, the refusal paths, the four maintenance CLIs, `scripts/check-tasklist-categories.mjs`** | Class C above, unchanged by the removals. Each is exercised by a test or is a stated contract that says it is unexercised. |
| **The 22 `ui/src` exports and the 12 `src-tauri` zero-reference items** | Class C above. Nothing removable in either language: no TS export has zero references including its own module, and `cargo build` emits no `dead_code` warning. |

### Two defects the removal surfaced but did not fix

Both are in `generate_docs.py`, both predate this sweep, and neither is dead code — fixing
either changes what a generator writes, which is a behaviour change and belongs to the docs
sweep that runs after this one. Recorded here so it is not re-discovered:

1. `main()` writes `docs/gap-analysis.md`, but the file it regenerates lives at
   `docs/explanation/gap-analysis.md`. Running `make docs` today writes a **second, orphaned
   copy** rather than updating the tracked one.
2. `gen_gap_analysis()` does not emit the `> **Status:** … · **Updated:** … · **Owner:** …`
   banner the tracked file carries, so a regeneration would silently drop it.

Both are why step 4's three prose lines were applied to
`docs/explanation/gap-analysis.md` directly after diffing it against a fresh
`gen_gap_analysis()` — that diff is exactly these two findings plus the three intended lines,
and nothing else.

---

## Class E — what the sweep could not decide

Everything below was reached by the three passes and **left in place**, not because it was
shown to be live but because this method cannot show it either way. An honest undecidable
list is a legitimate result of a sweep; a candidate promoted to Class A on the absence of
evidence is how a portfolio deletes a Prolog corpus reached by a path nobody found.

The rule applied to every row: **a static search over this tree returning nothing is not a
proof when the caller is not in this tree.** Each row names what would have to be checked
elsewhere to decide it.

| Undecidable | Why the search cannot settle it | What would decide it |
| --- | --- | --- |
| The 145 public symbols reachable only inside their own module (table below) | `pyproject.toml` ships `praxis` and `launcher` as installable packages, so any of them is `import`able by a consumer outside this repo. Pass 1 correctly did **not** flag them — each has in-file references — but "used only by its own module" and "published API" are the same shape from in here. | A search of every consumer of the distribution, which is not this repo. |
| `launcher.app:main` / `launcher.app:launch_lab` (`[project.scripts]`, `pyproject.toml:34–35`) | Reached through an **installed console script**, not a call site. `main` has no Python caller at all; `launch_lab`'s only in-tree caller is `Makefile:68`. A caller-count of zero here means "nobody in this repo shells out to it", which is expected of an entry point. | Whether anyone runs `praxis-launch` / `praxis-lab`. `src-tauri/src/library.rs` spawns the launcher, but by module path, not by console script. |
| The four `#[tauri::command]` functions — `app_info`, `launcher_status`, `lite_status`, `pick_folder` (`src-tauri/src/lib.rs:28–66`) | The only callers are **string literals across the FFI**: `invoke<AppInfo>("app_info")` in `ui/src/tauri.ts:22`, and three more in `tauri.ts:34,55` and `lite.ts:63`. `cargo` sees them referenced via `generate_handler!` and emits no `dead_code`; `tsc` sees a string. Neither compiler links the two ends, so neither would notice a rename on the other side. | A runtime check, or a test that drives the webview. Both compilers are green on a broken pair. |
| Every key of `build_model()`'s view model read only by `launcher/templates/index.html` | The Jinja template reaches 30 distinct names by string — `{{ d.covered }}`, `{{ cov['pct'] }}`, `{{ coverage['domainsGated'] }}`, `{{ t.status }}`, … — so a Python-side rename is invisible to `ast` and to `tsc` alike. The same keys reach `ui/src` through JSON, which is the second string boundary on the same data. | Rendering the page. `tests/test_launcher_api.py` covers the JSON half; the template half is a browser. |
| `scaffold_notebooks.reorg()` + `LEGACY_DOMAIN` / `LEGACY_ROOT_NOTEBOOKS` / `LEGACY_SECTION_DIRS` (`scaffold_notebooks.py:48–98`, ~50 lines) | Live by every static measure — `main()` calls it unless `--no-reorg` — but its **trigger no longer exists in this tree**: `python3 -c 'import scaffold_notebooks as s; …'` reports **0** of `LEGACY_ROOT_NOTEBOOKS` present and **0** of `LEGACY_SECTION_DIRS` present, so every run moves 0 items. No test names `reorg`. It is a completed one-shot migration whose remaining purpose is a *user's* older checkout. | The state of a disk this repo cannot see. Left in place: the cost is one no-op loop per scaffold run, and the failure mode of removing it is a silently un-migrated library. |
| The `x-agora-*` wire vocabulary (`praxis/llm.py:94–101`) | Four of the six constants — `AGORA_SERVED_MODEL_HEADERS`, `AGORA_PROVIDER_HEADERS`, `AGORA_ROUTE_HEADERS`, `AGORA_REQUEST_ID_HEADERS` — are read only inside `llm.py`, and every one is a **best-effort read of a reply another service writes**. A router that sends none of them leaves the client behaving exactly like a plain base-URL swap, so absence of traffic proves nothing about whether the header exists. | agora's own emitted headers. Consumed by reference on purpose (CLAUDE.md: "a URL in an env var, never an import"). |
| The chief record vocabulary (`praxis/headless.py:78–101`) — `RECORD_PREFIX`, `RUN_KEYS`, the `run-id`/`outcome`/`exit`/`summary` keys | The producer is `chief run --headless`, a different program. `tests/test_headless.py` drives a **fake** chief built from `FAKE_CHIEF_STDOUT` / `FAKE_CHIEF_EXIT` / `FAKE_CHIEF_RECORD` / `FAKE_CHIEF_STDERR`, so the tests pin what praxis does with a stream, never that chief still prints one. A key chief stopped emitting would look identical from here. | chief's own output. Same by-reference contract; `docs/reference/chief-powered-construction.md` is the prose half. |
| Code behind an env var nothing in-tree sets | `PRAXIS_NO_EMBED` is read only by `src-tauri/src/library.rs` and named nowhere but `CLAUDE.md` and `docs/reference/packaging.md`. `CHIEF_LOCAL_ENDPOINT` / `CHIEF_LOCAL_MODEL` are read by `praxis/headless.py` and set by no tracked file. `PRAXIS_ROOT` and `PRAXIS_PYTHON` are read by the shell. These are **operator switches**; a repo-wide grep finding only the reader is their normal state, not evidence. | Whether an operator sets them. Each is documented, which is the only in-tree evidence available. |
| The on-disk schemas — `storage.json`, `.praxis-sync.json`, `<slug>.checks.json`, `notebooks/coverage-floor.json`, `notebooks/ungated.json`, `progress/<learner>.json` | Every reader here also writes, so a field could be dead in the code and still be **live on a user's disk**, written by a shipped version. `storage.json` in particular lives outside the storage root it selects, so it survives every other reset. | A migration audit against released versions, not a search. |
| `praxis/s3.py` / `praxis/webdav.py` request shapes | `tests/mocks3.py` and `tests/mockdav.py` serve the real protocols on loopback, which pins the bytes praxis sends — but a header AWS or Nextcloud requires and the fakes tolerate is invisible from here, in both directions. | The real services. |

### The 145 shipped public symbols with no reference outside their own file

Reproduce with pass 1 modified to count **external** references only, over `praxis/`,
`launcher/`, `curriculum.py`, `nbstatus.py` and `scaffold_notebooks.py`, skipping `_`-prefixed
names:

```
public shipped symbols with ZERO references outside their defining file: 145
  praxis/jd.py: 15   praxis/jd_extract.py: 14   praxis/storage.py: 13   praxis/checks.py: 10
  praxis/llm.py: 9   praxis/suggest.py: 9   praxis/rubric.py: 8   praxis/lite.py: 7
  praxis/gateaudit.py: 6   praxis/headless.py: 5   nbstatus.py: 4   praxis/gap.py: 4
  praxis/s3.py: 4   praxis/tasklist.py: 4   scaffold_notebooks.py: 4   launcher/app.py: 3
  praxis/curriculum_gen.py: 3   praxis/library_index.py: 3   … and 13 more with 1–2 each
```

Most are tuning constants a module reads once (`MIN_PROMPT_CHARS`, `GIVEAWAY_MARGIN`,
`TARGET_CHARS`) — named rather than inlined so the threshold is reviewable, which is a reason
to keep them regardless of who imports them. The rest are functions with one in-file caller
(`save_jd`, `construction_targets`, `write_each`, `path_for`). **None is dead**: pass 1 flagged
none of them, because each is referenced inside its file. They are listed here because they are
the population an external consumer would be drawn from, and the honest statement is that this
sweep sized that population rather than cleared it.

## What a static search over this tree cannot see

The limits of the method, stated so the next sweep starts from them rather than rediscovering
them. Each is measured, not asserted.

1. **Cross-repo consumers.** The largest blind spot, and the one this portfolio has already
   been bitten by. `pyproject.toml` publishes `praxis` and `launcher`; `git ls-files` stops at
   the repo boundary. Every "0 references" in this document means *0 in this tree*.
2. **Nested definitions.** Pass 1's corpus is **module-level** defs, classes and `UPPER_CASE`
   assignments. Over the reduced tree that is 1,230 definitions — but `ast.walk` finds
   **1,489**, so **259 definitions were never candidates at all**. The whole of
   `launcher/app.py`'s route layer is in that gap: 27 handlers across 18 paths, every one
   defined inside `create_app()`. They are reachable by URL, never by name, and a handler
   deleted along with its client would leave no trace in pass 1 either way.
3. **String boundaries between languages.** Three in this repo, none of which any compiler
   spans: TS → Rust (`invoke("app_info")`), Python → Jinja (`{{ d.covered }}`), and
   Python ↔ TS over JSON (`/api/library`'s topic rows). Green `cargo build` + green
   `npm run build` + green `pytest` is compatible with a broken pair on any of the three.
4. **Reflection, and its absence.** Measured, and this one is good news: every `getattr` in
   the tree takes a **literal** attribute name (16 sites, all `getattr(x, "literal", default)`),
   and there is **no** `importlib`, `__import__`, `globals()`, `eval()` or `exec()` in any
   tracked `.py` outside `notebooks/`. The one dispatch table, `storage._RESOLVERS` /
   `_AVAILABLE` / `_WRITABLE` / `_ON_SELECT` / `_SYNC`, is keyed by a `kind` string that
   arrives from `storage.json` or the settings form — so its *values* are visibly referenced,
   but a `kind` no caller can produce would look identical to one in daily use.
   `register_backend()` widens that seam deliberately, for a caller who is by definition
   not in these tables.
5. **Generated and templated artifacts.** Measured negative for the largest one: **0 of the
   245 seed notebooks** import `curriculum`, `praxis`, `nbstatus` or `scaffold_notebooks`
   (`git ls-files 'notebooks/*.ipynb' | xargs grep -l …` → 0), so the notebook corpus keeps
   no Python symbol alive. What it *does* keep alive is metadata **keys** —
   `metadata.nbgrader.*` and `metadata.praxis.extension` — read by `praxis/checks.py` and
   written into files a user already has. `ui/dist` is build output and untracked, so nothing
   in it can be searched; `docs/explanation/gap-analysis.md` is generated by
   `generate_docs.py`, which is why editing one without the other reverts on the next
   `make docs`.
6. **Time.** Every count here is `chief/900-dead-code-paydown` at the commit named at the top.
   A search is a photograph; it is not a warranty, and it does not cover the branch that lands
   next week.

The one thing this sweep can say without qualification is what it *did* check, which is why
the Class C and Class E tables are the part worth keeping. Class A is 27 files that are gone;
these two are the reason the next sweep does not have to start over.

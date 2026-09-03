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

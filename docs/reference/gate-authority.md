# The gate's authority — which process holds the answer key

> **Status:** Current · **Updated:** 2026-08-22 · **Owner:** praxis

Praxis gates a tutorial behind knowledge checks, and a gate is only worth having if the
learner cannot open it themselves. Since [JupyterLite](jupyterlite.md) became the runtime,
a tutorial *runs* in a place the learner controls completely — a static site and a
WebAssembly kernel in their own browser. This is the one page that says where the gate
lives instead, and what may cross into that browser.

**The answer key is held by the Python core behind `launcher/app.py`, and by nothing
else.** Not the webview, not the JupyterLite site, not the Rust shell.

## The trust boundary

| Process | Trusted with the gate? | What it holds |
|---|---|---|
| The Python core — `launcher/app.py` over `praxis/checks.py` + `praxis/progress.py`, started by the shell from the embedded interpreter | **Yes** | The `<slug>.checks.json` answer keys, the recorded outcomes, grading, the derived unlocks |
| The Tauri shell — `src-tauri/`, Rust | Trusted as a process, but **holds no gate state** | It starts the core and serves static files; it never reads a key and has no unlock logic |
| The webview — `ui/` | **No** | What the core served it, and its own drafts |
| The JupyterLite site — `src-tauri/resources/jupyterlite` | **No** | Released tutorial bodies and a manifest, nothing graded |

The shell is trusted and still holds nothing on purpose. "Graded" is defined once, in
`praxis/checks.py`; a second implementation in Rust would be a second definition, and the
two would drift. The shell's job is to make the trusted process reachable, not to be it.

## What may cross to an untrusted surface

Four kinds of artifact cross, each through exactly one filter. Nothing else crosses.

| Artifact | Filter | What is withheld |
|---|---|---|
| One check, going out | `checks.learner_check()` | `answer`, `solution`, `test`, `expected` — never; `explanation` — only once that check has been graded |
| A section the learner has not reached | `progress.SectionGate.to_dict()` | All of it. A locked section serves `checks: []` — not the key, not even the question |
| A notebook — the JupyterLite site and `/render/<rel>` | `lite.browser_notebook()`, re-inspected by `lite.leak_failures()` | Every graded region: Praxis's check cells *and* nbgrader's companion `-tests` cell, whose assertions **are** the answer |
| One submission, coming **in** | `checks.learner_answer()` | Any verdict. A payload carrying `passed`, `outcome`, `graded_by`, `locked` … is refused **400**, not quietly ignored |

`learner_answer()` is the inbound twin of `learner_check()`, and the two are the same
promise read in both directions: one keeps the key from reaching the browser, the other
keeps the browser's *opinion* from being mistaken for a grade.

A rendered page is HTML the learner can read with devtools, so `/render/<rel>` is the same
untrusted surface the site is and gets the same notebook filter. It did not always: the 24
gated seed notebooks carry 168 graded cells whose assertions were plain text in any full
render. The questions are served by `/api/study/<rel>`, which knows what this learner has
unlocked; a static render cannot, so it shows the tutorial body and nothing graded.

`src-tauri/src/lite.rs` refuses any `*.checks.json` target with **403** before looking
anything up. `praxis/lite.py` stages only `.ipynb`, so a built site contains no key at all
— but that is a property of the last build, and the refusal is a property of the server.

## Grading happens in the trusted process. All of it.

There is one grading path — `checks.grade()` — and it runs where the key is:

- **`choice`** — compared against the check's `answer`, which never left the core.
- **`code`** — `checks.run_code_check()` runs the learner's submission against the check's
  `test` in a subprocess of the interpreter running the core. **The browser kernel is a
  scratchpad, never a grader.** A learner may draft in the JupyterLite pane and submit
  what they wrote; the run that decides is this one, and the hidden test is never shipped.
- **`short`** — graded by the model, from the core, with the marking key that never
  crossed the wire. No key configured is **503** — the one path that needs one.

The alternative was considered and declined: to auto-grade a `code` check in Pyodide, the
check's `test` would have to be in the browser, and a hidden test in the learner's hands
is the answer. Re-verifying a browser-produced result server-side would mean running the
submission in the core anyway, so it buys nothing and adds a claim to distrust.

The honest consequence, stated rather than hidden: **a `code` check is gradable exactly
when the Python core is running** — which is the same condition as the gate existing at
all. A bundle whose core cannot start serves no checks and records no outcomes; it is a
library with no gate, not a gate standing open. `ui/src/LiteLibrary.tsx` says so on the
page rather than showing an empty checks tab.

## Unlocks are derived, never stored

`progress.section_gates()` recomputes a notebook's locks from the recorded outcomes on
every request, and `progress.module_gates()` does the same for a module's topics. Nothing
on disk ever says "unlocked", so there is no flag to set — and a check the learner later
fails genuinely re-locks what it had opened. What *is* stored is the whole `CheckOutcome`,
the learner's answer verbatim included, because "did they pass" is a record, not a bit.

The browser holds no part of that rule. `ui/src/study.ts` types the launcher's reply and
`ui/src/KnowledgeChecks.tsx` renders it; both compute `locked` never. A disabled button is
not the gate — posting at a check in a section the learner has not reached is refused
**423** without being graded, and a submission for a notebook locked behind an earlier
topic is refused the same way.

## How this page is enforced

`tests/test_gate_authority.py` asserts the claims above against the code rather than
trusting the prose: the filters are the only crossings, a forged verdict is refused, a
forged pass records a failure and unlocks nothing, a locked section's response contains no
question text, `/render` and the site carry no graded region, and the frontend derives no
lock. It reads this file too — a claim removed here has to be removed there.

## Related

- [JupyterLite — the tutorial runtime in the browser](jupyterlite.md) — the untrusted runtime, and how the site is staged
- [Packaging Praxis](packaging.md) — what a bundle carries, and how the core reaches it
- [jupyterquiz — assessed and declined](../explanation/jupyterquiz-assessment.md) — the adoption this boundary refused

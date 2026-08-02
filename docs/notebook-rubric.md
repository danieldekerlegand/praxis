# Notebook Completion Rubric

Every study notebook is a **self-contained refresher** for one topic. This rubric is the
definition of "complete" and is embedded into every Ralph task. The automated gate is
[`tests/test_notebooks.py`](../tests/test_notebooks.py).

## Required structure

A complete notebook keeps the eight scaffold sections (you may add more):

1. **What & Why** — what it is, the problem it solves, when to reach for it (and when not to).
2. **Mental Model** — the one analogy or diagram that makes it click.
3. **Key Concepts** — the handful of terms/ideas you must hold in your head.
4. **Setup** — install/prereqs. For Python-runnable topics, a real `%pip install ...`.
5. **Worked Examples** — **at least two** concrete examples (see runnable vs conceptual below).
6. **Gotchas & Pitfalls** — the mistakes that actually bite people.
7. **When to Use vs Alternatives** — honest trade-offs against the competing options.
8. **Resources** — official docs plus 2–3 high-signal links with **real URLs** (no `[Link]`).

## Runnable vs conceptual

Each topic is tagged `runnable` in `curriculum.py`:

- **`runnable: true`** — at least two **executed** code cells that run top-to-bottom in a fresh
  kernel and show real output. Prefer small, self-contained examples (tiny models/data, CPU-OK).
  Topics needing an API key or large download: gate the network cell behind a clear
  `if os.getenv("...")` check and still show the call shape, so the notebook executes either way.
- **`runnable: false`** — the tech can't be driven from a Python notebook (game engines, VR SDKs,
  GUI/IDE products, another language). Use CLI commands, config/code snippets, pseudo-code, and a
  one-line note stating it isn't Python-runnable and why. No fake `print()` theater.

## Hard requirements (the gate)

- **No placeholder text** — none of the scaffold/legacy markers remain (`TODO`,
  `provide description here`, `add code here`, `[Link]`, `Benefit 1`, `Feature 1 | Description`, …).
- **Valid `nbformat`** — the file parses and validates.
- **All eight section headers present.**
- **Substantive** — meaningfully more than the scaffold (the heuristic floor is ~6 KB of prose;
  write for understanding, not for a byte count).
- **Runnable notebooks execute cleanly** — `jupyter nbconvert --to notebook --execute` succeeds
  (allowed to be skipped in CI when a heavy/optional dependency is missing, but the code must be
  correct as written).

## Style

- Write like you're refreshing a smart colleague: concise, concrete, opinionated where it helps.
- Show the smallest example that teaches the idea; link out for exhaustive API surface.
- When a topic overlaps another notebook, cross-link it rather than duplicating.

## Knowledge checks (the learner-side gate)

A finished notebook is not yet a *gated* tutorial. Each one is paired with a
`<slug>.checks.json` beside it (`praxis/checks.py`, written as the second half of
construction) holding the questions a learner must pass to unlock the next section.

- **One check per gated section, minimum** — the eight rubric sections minus Setup and
  Resources, which teach nothing a learner can be tested on.
- **A mix of kinds**, at least one of each the topic can carry:
  - `choice` — multiple choice, ≥ 3 options, `answer` is the 0-based index. Auto-graded.
  - `code` — write code that satisfies the check's `test`. Auto-graded by running the
    learner's submission and the assertions together in a subprocess. Only on
    `runnable: true` topics.
  - `short` — a written answer, graded by the model against the check's `expected`
    marking key, with the learner's answer recorded verbatim on the outcome.
- **The answer key never lives in the notebook** — that is why the checks are a sibling
  file and not a cell.

Hard requirements, the same shape as the notebook gate (`praxis.checks.checkset_failures`
is the machine-checkable definition, and a set that fails it is never written):

- Every gated section is covered, and the set holds each kind the topic can carry.
- A `code` check's `test` really asserts, and its reference `solution` is **run** and
  must pass that test — a check nobody has proved gradable is not written.
- A `choice` check's answer indexes a real option, with no duplicate options.
- A `short` check's `expected` spells out what a correct answer must say, specifically
  enough for another grader to mark against.

### What the checks gate

`praxis/progress.py` turns a set of checks into a progression, and the whole rule is one
sentence: **a section is unlocked when every check in every earlier section has a passing
outcome.** The first gated section is always open, the order is the rubric's own, and the
same rule one level up orders a module: a topic is locked while an earlier topic in it
still has unpassed checks. A notebook with no checks beside it gates nothing, which is
what keeps the seed library open.

Three things make the gate real rather than decorative:

- **An unlock is derived, never stored.** It is recomputed from the recorded outcomes on
  every request, so there is no flag to set — and a check the learner later gets wrong
  genuinely closes what it had opened.
- **A locked section hands over nothing** — not the answer key (never, to anyone: see
  `checks.learner_check`), and not even the question. `POST /api/study/<rel>` answers
  **423** for a check the learner has not reached, instead of grading it.
- **What is recorded is the outcome, not a boolean** — the learner's answer verbatim, who
  graded it and when, because "did they pass" is a record.

Progress is one JSON file per learner under `PRAXIS_PROGRESS_DIR` (default `.praxis/`),
so it survives closing the app.

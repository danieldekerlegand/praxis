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

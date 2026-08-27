# What a gated domain costs

The gating machinery — `praxis/backfill.py`, `praxis/coverage.py`, `praxis/gateaudit.py`,
`praxis/regate.py` — shipped weeks before any batch was run with it. This document is the
first measurement of actually running it, end to end, over one seed domain, so that the
remaining scope is a decision rather than a guess.

## The run

`notebooks/01-symbolic-ai-logic`, 15 notebooks, taken from 0 gated to 15 gated. It was
chosen over the smaller domains because it exercises both halves of the `runnable` rule:
14 of its topics are Python-runnable and must carry a `code` check, and
`description-logic-reasoners` is conceptual and must carry none. A domain of 9 would have
been cheaper and would have proved less.

| | |
|---|---|
| Notebooks gated | 15 of 15 |
| Checks written | 90 — 45 `choice`, 31 `short`, 14 `code` |
| Checks per notebook | 6, one per gated rubric section |
| `gateaudit` findings | 0 of 90 |
| `nbgrader validate` failures | 0 |
| Machine time, whole domain | 47.1 s — 3.1 s per notebook |
| Authored content | ~157 kB of JSON, ~10.5 kB per notebook |
| Notebook prose read to author it | ~232 kB, ~15.4 kB per notebook |
| Drafts rejected by the write path | 2 of 15, one round each |

**Machine time is not the cost.** 3.1 s per notebook is the shipped write path doing its
work: `checkset_failures(verify_code=True)` runs each `code` check's reference solution
against its own test in a subprocess, `gateaudit`'s triviality rules run the same test
against an empty submission and against the starter stub, and `publish_graded_cells`
annotates a staging copy and hands it to `nbgrader validate`. Four subprocess launches per
runnable notebook, and the whole domain finishes inside a minute.

**Authoring is the cost**, and it is dominated by reading. Writing a check that a learner
cannot pass by pattern-matching the page requires knowing what the page says: ~15 kB of
prose per notebook in, ~10 kB of questions, marking keys, reference solutions and hidden
tests out. Scaled at face value, the remaining 206 ungated notebooks are roughly 3.2 MB of
prose to read and 2.2 MB of gate to write — which is why **§ Scope** below is a decision
and not a formality.

**Review is cheap because the grader is strict.** 2 of 15 drafts were rejected on their
first pass and both were caught by the machine, not by a reader:

- a `code` check whose reference solution did not pass its own test — the assertion
  encoded a wrong expectation about unification, and `run_code_check` said so;
- a propagation rule that was *unsound*: "a value surviving in only one variable's domain
  forces that variable" is true for a permutation constraint and false for a general
  all-different, where a value may simply go unused. The reference solution disagreed with
  the test on a one-variable input and the run failed. It was replaced with the Hall-set
  argument, which is what a real propagator computes.

Both are the anti-fabrication rule earning its keep: content that fails the grader is never
written, and the failure comes back as a sentence naming what to fix.

## What the runner got wrong, and what was fixed in the runner

One defect, and it is the reason the batches never ran: **the runner could not be driven
without a live provider.** `backfill_domain` → `construct_each` → `generate_checks` is a
grader wrapped around one HTTP call, and with no key configured the whole pipeline is
unreachable — including the grading, which is the part that is actually the product.

The fix is `praxis/authored.py`, and it changes no gating rule. `generate_checks` reads
exactly two things off its client, `complete(prompt, system=…)` and `config.model`, so an
`AuthoredClient` that serves a reply from a file beside the notebook is a complete
substitute for the provider:

```
python3 -m praxis.authored prompts 01-symbolic-ai-logic   # what the runner would ask
python3 -m praxis.authored status  01-symbolic-ai-logic   # draft/gate state per topic
python3 -m praxis.authored run     01-symbolic-ai-logic   # grade the drafts, write gates
```

Everything downstream is the shipped path, unchanged and unbypassed: normalization,
`checkset_failures` with the subprocess run and the measured triviality rules,
`publish_graded_cells`, `nbgrader validate`, and the rule that a draft failing any of it is
**not written** while the notebook is left byte-identical. `tests/test_authored.py` pins
each of those refusals against a file rather than against a model.

A draft is the author's working copy — `<slug>.checks.draft.json`, git-ignored, because the
accepted `<slug>.checks.json` is the durable artifact and a tracked draft would be a second
copy of the same questions with nothing keeping the two in sync.

Three tests in the suite also had to move: `test_gateaudit`, `test_regate` and
`test_launcher_api` each pinned the shipped corpus by exact count (24 gates, 144 checks, "the
first seed domain is ungated"). They failed *because coverage rose*, which is the tool
working. They now assert a floor plus the property the count stood in for — nothing flagged,
every gate holds — and select by state rather than by position.

## Scope

Per-notebook cost is now known and it is authoring, not compute. `praxis.coverage` reports
the position after this run; what the remaining domains are worth, and which of them are
worth gating at all, is decided against these figures rather than against an assumption.

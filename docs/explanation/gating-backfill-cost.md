# What a gated domain costs

The gating machinery — `praxis/backfill.py`, `praxis/coverage.py`, `praxis/gateaudit.py`,
`praxis/regate.py` — shipped weeks before any batch was run with it. This document is the
measurement of actually running it, end to end, so that the remaining scope is a decision
rather than a guess: first over one domain, then over the five others that had no gate at
all, and then the recorded decision about what is left.

## The first run

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
tests out. Scaled at face value, the 206 notebooks still ungated after that first domain
were roughly 3.2 MB of prose to read and 2.2 MB of gate to write — which is why the scope
sections below are a decision and not a formality.

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

A fourth moved for the same reason once every domain had a gate: `test_launcher_api`'s
"a module carrying no gate locks nothing" had been reading it off the shipped library,
and after the backfill there is no fully ungated seed module left to point at. The claim
is a property of `progress.module_gates()`, so it is now asserted there. The rule is the
thing under test; the library is not.

## The rest of the zero-coverage domains

The first domain's figures held across the other five, which is the useful result: the
cost is stable and scales with notebook count, so the remaining scope really is arithmetic
rather than a guess.

| Domain | Notebooks | Checks | Machine time | Per notebook | `gateaudit` |
|---|---|---|---|---|---|
| `01-symbolic-ai-logic` | 15 | 90 | 47.1 s | 3.1 s | 0 flagged |
| `07-proprietary-coding-ai` | 9 | 54 | — | — | 0 flagged |
| `10-data-analysis-research` | 15 | 90 | — | — | 0 flagged |
| `09-procedural-generation` | 16 | 96 | — | — | 0 flagged |
| `04-agentic-ai` | 16 | 96 | 45.3 s | 2.8 s | 0 flagged |
| `05-speech-audio` | 22 | 132 | 64.5 s | 2.9 s | 0 flagged |
| **Total** | **93** | **558** | — | **~2.9 s** | **0 flagged** |

Every one of the six domains the band was opened over — the ones reporting 0% — is now at
100%. `python3 -m praxis.coverage` reports **117 of 245 (48%), in 14 of 14 domains**, up
from 24 of 245 in 8 of 14. Across the whole library `python3 -m praxis.gateaudit` flags 0
of 702 checks, `python3 -m praxis.regate` reports 117 of 117 holding the write path's own
bar, and `scripts/validate_nbgrader.py notebooks` reports 0 failures over 117 notebooks.

Two things stayed true at six times the scale. Machine time per notebook did not move
(2.8–3.1 s), because it is four subprocess launches and not a model call. And the write
path kept catching what a reader would not: drafts were rejected for a reference solution
that disagreed with its own test, for an expected frame count that was off by one, for a
tolerance too tight for the arithmetic underneath it, and for an assertion about a mel
filterbank that was false at the resolution actually used. In every case the failure came
back as a sentence naming the check and the line.

The code checks were written as **stdlib re-implementations of each notebook's own
mechanism** — the handshake that gates a tool call, the durable task resumed by id, the
state reducer that clobbers without a merge rule, the observation the model is not allowed
to write for itself, the blank that lets a double letter survive, the byte-not-character
request limit, the soft alignment that has a gradient where a repeat has none. That is the
property `gateaudit` cannot check for you and the reason the domain choice matters: a check
a learner can pass by recognising prose is not a gate.

## Scope: what is left, and why it is deferred rather than cut

128 notebooks remain, all of them in four **partially** gated domains. None of them is
unsuitable for gating — every one is ✅, and nothing about them makes a real check
impossible — so this is a scheduling decision, not an exclusion:

| Domain | Ungated | Position |
|---|---|---|
| `02-ai-ml-tooling` | 14 | first — smallest, and the tooling most learners meet first |
| `08-architectures` | 22 | second — the strongest remaining code-check material |
| `03-llm-inference-training-optimization` | 28 | third — 5 already gate |
| `11-devops-mlops-infra` | 64 | last — more than the other three combined, and the hardest to make non-trivial |

At ~15 kB of prose read and ~10 kB of gate written per notebook, that is roughly **2.0 MB
to read and 1.3 MB to write**. The constraint is authoring attention, not compute and not
review: at 2.9 s per notebook the machine time for all 128 is about six minutes.

That decision is **on disk, not just in this document**. `notebooks/ungated.json` is the
tracked register and `praxis/ungated.py` grades it against the live library, so an entry
naming a domain that no longer has an ungated notebook in it is reported as stale rather
than believed. `python3 -m praxis.coverage` now splits the complement of `gated` in two —
*ungated by recorded decision* and *unaccounted for* — and the second number is the one to
watch. It is currently **0**: every notebook without a gate has a dated reason behind it.

The register deliberately changes nothing about what the batch selects. A deferred notebook
is still in `backfill_targets()`, because a register that quietly shrank the queue would
turn "we decided to wait" back into "we forgot" — which is the confusion it exists to
remove.

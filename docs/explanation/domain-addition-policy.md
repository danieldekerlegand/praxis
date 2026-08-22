# Seed Domain Addition Policy

Seed domains are numbered in order from `01` through `15`, with `06` permanently
reserved as a historical hole. A new seed domain appends the next free number (`16`
or higher); it must never reuse `06` or renumber an existing domain.

Adding a domain is a three-part repository change:

1. Add a `Domain` entry to `curriculum.py`'s `DOMAINS`, using the new numbered
   directory and a manifest of `Topic` entries (or the documented filesystem source
   for a legacy collection).
2. Add the matching `notebooks/NN-slug/` directory and scaffolded or completed
   notebooks.
3. Add a matching coverage heading to `docs/explanation/gap-analysis.md`. A topic is
   covered only after the shipped rubric and knowledge-check graders pass; a status
   marker must never be used to bypass either grader.

The consistency check in `praxis.promote.domain_numbering_failures` compares the
manifest to the on-disk numbered directories and rejects reuse of `06`.

## Promoting recommended additions

The recommended additions in section 2 of the gap analysis are already represented
as scaffolded `Topic(recommended=True)` entries. Run the repository maintenance
promotion path for one topic:

```text
python -m praxis.promote 02-ai-ml-tooling jax-flax
```

Promotion delegates to `construct_topic(..., checks=True)`, requires a complete
notebook and a valid checkset, and only then moves the exact entry into section 1.
Failures leave the gap-analysis backlog unchanged.

# Seed refresh policy

The notebooks under `notebooks/` are shipped product assets. They are never
rewritten by the running app. Refreshing one is repo maintenance: a maintainer
runs the refresh entry point, reviews the resulting diff, and commits the
accepted notebook.

The audit report has exactly two possible maintenance outcomes:

1. **FLAGGED-FOR-HUMAN** is the default. The report names the notebook, the
   measured dead URL or code/gate failure, and the grader sentence. A maintainer
   decides whether the seed needs new content; no file is changed.
2. **FORCE-REGENERATE** requires an explicit, per-notebook `--force` (or
   `force=True`) opt-in. It delegates to the shipped `construct_topic` pipeline
   with `force=True`. The candidate must pass `construction_failures` before the
   constructor writes anything. A failed candidate therefore leaves the
   existing seed byte-identical.

An un-flagged `✅` notebook is never a regeneration target. This preserves the
constructor's skip-if-✅ invariant: only a flagged notebook and an explicit
force request can reach the forced constructor. The command is intentionally
run from the repository, for example:

```sh
python -m praxis.refresh notebooks/02-ai-ml-tooling/pytorch.ipynb --json
python -m praxis.refresh notebooks/02-ai-ml-tooling/pytorch.ipynb --force --json
```

The second command's output is a reviewable working-tree change. It does not
create an in-app write path or silently alter any other seed.

# JupyterLite — the tutorial runtime in the browser

> **Status:** Current · **Updated:** 2026-08-22 · **Owner:** praxis

Praxis's north star is *demonstrated understanding, not scrolling*, and the first thing
a learner met was a toolchain: install Python, install the launch extra, register a
kernel, then run `praxis-lab` **and** `praxis-launch` in two terminals. That is the whole
first-run cost of reading one notebook.

[JupyterLite](https://github.com/jupyterlite/jupyterlite) (BSD-3-Clause) is a full
JupyterLab that runs entirely in the browser on a [Pyodide](https://pyodide.org) kernel —
CPython compiled to WebAssembly. There is no server, no local interpreter and no kernel
to register. Praxis **adopts** it as the runtime for notebook content.

## What is adopted, and what deliberately is not

JupyterLite is the *runtime*. It is **not** the gate, and cannot be.

The gate is server-side on purpose: `checks.learner_check()` is the only way a check
reaches a client, a locked section is served **no checks at all** (not the answer key,
not even the question), and `POST /api/study/<rel>` answers **423** for a section the
learner has not reached. A JupyterLite site is a static directory the learner controls
completely — shipping the gate into it would hand every learner the answer key, and *a
disabled button is not the gate*.

So the split is:

| | Where it runs | What it holds |
|---|---|---|
| **Tutorial content** — the eight rubric sections and their code | The browser, on Pyodide | The released notebook body, nothing graded |
| **The gate** — questions, grading, unlocks | A process the learner does not control: the Tauri backend / the embedded interpreter | The answer key, the recorded outcomes, the derived unlocks |

`praxis/lite.py` is that boundary, and it is stricter than `learner_check()` rather than
equal to it: `browser_notebook()` removes **every** graded region — Praxis's own check
cells (`metadata.praxis.extension == "checks"`), nbgrader's `grade`/`solution`/`locked`/
`task` cells, and the companion `-tests` cell whose assertions *are* the answer — and
`stage_contents()` copies only `.ipynb` files, so the `<slug>.checks.json` answer key
never travels. `leak_failures()` re-inspects the artifact **after** stripping and staging
**raises** on any failure, so a notebook that still carries a reference solution or a
hidden test stops the build instead of reaching the browser. That is the constructor's
"content that fails the grader is never written", one level out.

## Not every tutorial can run in a browser

Pyodide provides numpy, pandas, matplotlib, scipy, sympy, scikit-learn and ~300 other
importable names. It does not provide `torch`, `transformers`, `vllm` or a socket.

A tutorial served into a kernel that will die at its first import is worse than one
honestly reported as unavailable, so `requirements()` resolves each notebook's top-level
imports against a **pinned** Pyodide package index and `stage_contents()` stages only what
resolves. The rest is recorded in the site's manifest as `unavailable-in-browser`, naming
the modules that made it so. As the seed library ships:

| | Seed notebooks |
|---|---|
| runnable in the browser | **101** |
| `unavailable-in-browser` | **144** |
| total | **245** |

The index is vendored at `praxis/data/pyodide-packages.json` — the `imports` field of the
pinned release's own `pyodide-lock.json`, so `PIL` resolves to `Pillow` rather than being
guessed from a name. It is **vendored rather than fetched**, because a build that asks the
network what "available" means is not reproducible. Regenerate it with:

```bash
python3 -m praxis.lite index --pyodide v314.0.5      # or --lock <a pyodide-lock.json on disk>
```

## Building the site

```bash
make build-lite                     # or: scripts/build-jupyterlite.sh
scripts/build-jupyterlite.sh --check    # report the plan, build nothing
scripts/build-jupyterlite.sh --force    # rebuild an already-staged site
```

`make build` runs it before `build-ui`, and `make bundle` depends on it. It is
stamp-guarded: a site already staged for the current pins is left alone, so it costs a
second on every build but the first.

The output is **build output, not a dependency**: it lands in
`src-tauri/resources/jupyterlite` beside the embedded Python runtime, which is gitignored
wholesale (see [Packaging Praxis](packaging.md)). ~72 MB.

| Pinned in `praxis/lite.py` | Version |
|---|---|
| `jupyterlite-core` | 0.8.3 |
| `jupyterlite-pyodide-kernel` | 0.8.5 |
| `jupyter-server` (build-time only — the contents addon requires it) | 2.14.2 |
| Pyodide (loaded by the kernel) | v314.0.5, CPython 3.14.2 |

`scripts/build-jupyterlite.sh` reads those through `python3 -m praxis.lite pins`, so the
script cannot drift from what `tests/test_lite.py` asserts was adopted. Its own Python
lives in an isolated `.lite-venv`: `jupyterlite-core` is a build dependency of the site,
never of the product, and putting it in the repo's `.venv` would make the launch extra
carry it forever.

### What the site contains

```
src-tauri/resources/jupyterlite/
  index.html  lab/  repl/  tree/       JupyterLab, as static files
  extensions/@jupyterlite/pyodide-kernel-extension/
  files/<domain>/<topic>.ipynb         the released tutorials — 101 of them
  api/contents/all.json                JupyterLite's own contents index
  praxis-lite.json                     the manifest: pins, and every tutorial's verdict
```

`praxis-lite.json` is what the shell reads to say which tutorials run in the browser and
which are honestly unavailable there — the same not-measured-rather-than-silently-zero
discipline `praxis/coverage.py` uses for gates.

### The kernel and the network

The pinned kernel loads Pyodide itself from `cdn.jsdelivr.net`, so a *first* run needs
network access even though nothing is installed locally. Everything after it is served
from the browser's cache. Bundling Pyodide into the site (`jupyter lite build --pyodide
<dist>`) is JupyterLite's own supported path for a fully offline site and adds ~250 MB;
it is not taken here.

## Related

- [Packaging Praxis](packaging.md) — what a bundle carries and how it is built
- [Notebook Completion Rubric](../explanation/notebook-rubric.md) — what a tutorial is
- [Storage — where your work is kept](storage.md) — why generated subjects are not staged here

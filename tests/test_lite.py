"""JupyterLite delivery — what crosses into the browser, and what is honestly withheld.

A JupyterLite site is a static directory the learner controls completely: there is no
server behind it to refuse anything. So the two things worth asserting about
`praxis/lite.py` are exactly the two the tasklist would not duck —

- **nothing that gates crosses.** Every graded region is removed before a notebook is
  staged, no answer key is copied, and the check runs on the artifact rather than the
  source, so it measures what is actually written.
- **nothing is served that cannot run.** Pyodide has numpy and does not have torch, and
  a tutorial staged into a kernel that dies at its first import is the silently-zero
  failure the rest of the repo refuses. It is reported unavailable-in-browser instead.

The last test in this file is the only one that needs a built site (60+ MB, one
`jupyter lite build`), and it skips itself when there is none — the same discipline the
launcher tests use for the launch extra.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from praxis import lite

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build-jupyterlite.sh"


def notebook(*cells: dict, metadata: dict | None = None) -> dict:
    return {
        "cells": list(cells),
        "metadata": metadata if metadata is not None else {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def code(source: str, **metadata) -> dict:
    return {"cell_type": "code", "source": [source], "metadata": metadata,
            "execution_count": None, "outputs": []}


def markdown(source: str, **metadata) -> dict:
    return {"cell_type": "markdown", "source": [source], "metadata": metadata}


# --- the pins ---------------------------------------------------------------


def test_one_pinned_jupyterlite_release_named_in_one_place():
    """The adoption is a version, not a moving target — and the script reads it here."""
    assert lite.JUPYTERLITE_CORE.count(".") == 2
    assert lite.JUPYTERLITE_PYODIDE_KERNEL.count(".") == 2
    pins = subprocess.run([sys.executable, "-m", "praxis.lite", "pins"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
    assert f"jupyterlite-core=={lite.JUPYTERLITE_CORE}" in pins
    assert f"jupyterlite-pyodide-kernel=={lite.JUPYTERLITE_PYODIDE_KERNEL}" in pins
    assert f"jupyter-server=={lite.JUPYTER_SERVER}" in pins


def test_the_pyodide_index_is_vendored_not_fetched():
    """A build that asks the network what "available" means is not reproducible."""
    document = lite.index_document()
    assert document["pyodide"].startswith("v")
    assert document["python"]
    # The import->package mapping is pyodide-lock.json's own, so aliases are right.
    assert lite.pyodide_imports()["PIL"] == "Pillow"
    assert "numpy" in lite.pyodide_imports()
    assert {"json", "pathlib", "dataclasses"} <= lite.pyodide_stdlib()


def test_build_script_check_reports_the_plan_and_builds_nothing(tmp_path):
    result = subprocess.run(["bash", str(SCRIPT), "--check"], cwd=ROOT,
                            env={**os.environ, "PRAXIS_LITE_SITE": str(tmp_path / "site")},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"jupyterlite-core=={lite.JUPYTERLITE_CORE}" in result.stdout
    assert "check-only — nothing built" in result.stdout
    assert not (tmp_path / "site").exists()


# --- what a tutorial needs --------------------------------------------------


def test_a_notebook_pyodide_can_serve_is_available():
    nb = notebook(code("import json\nimport numpy as np\nfrom matplotlib import pyplot"))
    needs = lite.requirements(nb)
    assert needs.available and needs.status == lite.AVAILABLE
    assert needs.missing == ()
    assert set(needs.packages) == {"numpy", "matplotlib"}
    assert "json" not in needs.modules          # stdlib is not a dependency to resolve


def test_a_notebook_pyodide_cannot_serve_names_what_is_missing():
    """Not-measured rather than silently-zero: say torch, don't serve a dead kernel."""
    nb = notebook(code("import torch\nimport numpy as np"))
    needs = lite.requirements(nb)
    assert not needs.available and needs.status == lite.UNAVAILABLE
    assert needs.missing == ("torch",)
    assert needs.packages == ("numpy",)


def test_an_unparseable_cell_does_not_decide_availability():
    """Tutorials show elided code; compilability is rubric.construction_failures' job."""
    nb = notebook(code("this is (not python"), code("import numpy"))
    assert lite.requirements(nb).available


# --- what may cross into the browser ----------------------------------------


GATED = notebook(
    markdown("## Concepts\nA diffusion pipeline has four collaborators.",
             nbgrader={"grade": False, "solution": False, "locked": False, "grade_id": "source-0001"}),
    code("import numpy as np\nnp.array([1])",
         nbgrader={"grade": False, "solution": False, "locked": False, "grade_id": "source-0002"}),
    markdown("Why does `diffusers` exist?",
             nbgrader={"grade": True, "solution": True, "locked": False, "grade_id": "q-1"},
             praxis={"extension": "checks", "kind": "short", "grade_id": "q-1"}),
    code("def cfg(u, c, s):\n    ...\n",
         nbgrader={"grade": True, "solution": True, "locked": False, "grade_id": "q-2"},
         praxis={"extension": "checks", "kind": "code", "grade_id": "q-2"}),
    # nbgrader's companion autograder-tests cell: no praxis namespace, and its
    # assertions ARE the answer.
    code("assert cfg([1], [2], 0.0) == [1], 'scale 0 ignores the prompt'",
         nbgrader={"grade": True, "solution": False, "locked": True, "grade_id": "q-2-tests"}),
)


def test_browser_notebook_removes_every_graded_region():
    released = lite.browser_notebook(GATED)
    assert [c["metadata"]["nbgrader"]["grade_id"] for c in released["cells"]] == [
        "source-0001", "source-0002",
    ]
    assert "scale 0 ignores the prompt" not in json.dumps(released)
    assert lite.leak_failures(released) == []


def test_browser_notebook_does_not_mutate_its_source():
    before = json.dumps(GATED)
    lite.browser_notebook(GATED)
    assert json.dumps(GATED) == before


def test_leak_failures_names_the_gate_it_found():
    failures = lite.leak_failures(GATED, "diffusers.ipynb")
    assert any("q-1" in f for f in failures)
    assert any("q-2-tests" in f and "locked" in f for f in failures)
    assert all(f.startswith("diffusers.ipynb: ") for f in failures)


def test_leak_failures_catches_an_authored_source_staged_by_mistake():
    """The authored notebook carries nbgrader's regions; the released one has none."""
    authored = notebook(code(
        "def add(a, b):\n"
        "### BEGIN SOLUTION\n    return a + b\n### END SOLUTION\n"
        "### BEGIN HIDDEN TESTS\nassert add(1, 2) == 3\n### END HIDDEN TESTS"))
    assert any("BEGIN SOLUTION" in f for f in lite.leak_failures(authored))
    assert any("BEGIN HIDDEN TESTS" in f for f in lite.leak_failures(authored))


def test_leak_failures_catches_an_answer_key_in_notebook_metadata():
    keyed = notebook(metadata={"praxis": {"extension": "checks", "checks": [{"answer": 1}]}})
    assert any("answer key" in f for f in lite.leak_failures(keyed))


# --- staging ----------------------------------------------------------------


def library(tmp_path: Path) -> list[tuple[str, Path]]:
    """A two-notebook library on disk, one gated and one Pyodide cannot serve."""
    root = tmp_path / "notebooks" / "01-demo"
    root.mkdir(parents=True)
    (root / "gated.ipynb").write_text(json.dumps(GATED))
    (root / "gated.checks.json").write_text(json.dumps(
        {"checks": [{"id": "q-1", "answer": "because pipelines", "solution": "x", "test": "assert x"}]}))
    (root / "heavy.ipynb").write_text(json.dumps(notebook(code("import torch"))))
    return [("01-demo/gated.ipynb", root / "gated.ipynb"),
            ("01-demo/heavy.ipynb", root / "heavy.ipynb")]


def test_stage_contents_serves_the_released_notebook_and_no_answer_key(tmp_path):
    report = lite.stage_contents(tmp_path / "contents", library(tmp_path))

    staged = sorted(p.relative_to(tmp_path / "contents").as_posix()
                    for p in (tmp_path / "contents").rglob("*") if p.is_file())
    assert staged == ["01-demo/gated.ipynb"]          # the sidecar never travels
    served = json.loads((tmp_path / "contents" / "01-demo" / "gated.ipynb").read_text())
    assert lite.leak_failures(served) == []
    assert "because pipelines" not in json.dumps(served)
    assert "Why does `diffusers` exist?" not in json.dumps(served)

    assert [t.rel for t in report.available] == ["01-demo/gated.ipynb"]
    assert [t.rel for t in report.unavailable] == ["01-demo/heavy.ipynb"]
    assert report.unavailable[0].missing == ("torch",)


def test_stage_contents_refuses_a_notebook_that_would_still_leak(tmp_path):
    """Content that fails the grader is never written — the constructor's rule, one out."""
    root = tmp_path / "01-demo"
    root.mkdir(parents=True)
    leaky = notebook(code("x = 1\n### BEGIN SOLUTION\nx = 42\n### END SOLUTION"))
    (root / "leaky.ipynb").write_text(json.dumps(leaky))
    with pytest.raises(lite.LiteError) as err:
        lite.stage_contents(tmp_path / "contents", [("01-demo/leaky.ipynb", root / "leaky.ipynb")])
    assert "leaky.ipynb" in str(err.value)
    assert not (tmp_path / "contents" / "01-demo").exists()


def test_manifest_declares_the_dependency_set_and_the_pins(tmp_path):
    report = lite.stage_contents(tmp_path / "contents", library(tmp_path))
    path = lite.write_manifest(report, tmp_path / lite.MANIFEST_NAME)
    manifest = json.loads(path.read_text())
    assert manifest["jupyterlite"] == lite.JUPYTERLITE_CORE
    assert manifest["pyodideKernel"] == lite.JUPYTERLITE_PYODIDE_KERNEL
    assert manifest["counts"] == {"total": 2, lite.AVAILABLE: 1, lite.UNAVAILABLE: 1}
    heavy = next(t for t in manifest["tutorials"] if t["rel"].endswith("heavy.ipynb"))
    assert heavy["status"] == lite.UNAVAILABLE and heavy["missing"] == ["torch"]


def test_library_sources_uses_the_same_rel_as_the_launcher():
    """A manifest entry must name the topic the shell already knows.

    `launcher.app` builds a seed topic's `rel` as its path relative to the notebooks
    root; anything else and `/render/<rel>` and the site would disagree about a topic.
    """
    from curriculum import NOTEBOOKS_DIR

    sources = lite.library_sources()
    assert sources, "the seed library should not be empty"
    for rel, path in sources:
        assert path.is_file()
        assert rel == path.relative_to(NOTEBOOKS_DIR).as_posix()


# --- the built site ---------------------------------------------------------


@pytest.mark.skipif(not (lite.SITE_DIR / "praxis-lite.json").is_file(),
                    reason="no JupyterLite site built (scripts/build-jupyterlite.sh)")
def test_the_built_site_carries_jupyterlite_a_pyodide_kernel_and_released_notebooks():
    site = lite.SITE_DIR
    for asset in ("index.html", "jupyter-lite.json", "lab/index.html",
                  "api/contents/all.json", "praxis-lite.json"):
        assert (site / asset).is_file(), f"the built site is missing {asset}"
    extensions = {p.name for p in (site / "extensions").rglob("*") if p.is_dir()}
    assert "pyodide-kernel-extension" in extensions

    manifest = json.loads((site / "praxis-lite.json").read_text())
    assert manifest["jupyterlite"] == lite.JUPYTERLITE_CORE

    served = sorted((site / "files").rglob("*.ipynb"))
    assert len(served) == manifest["counts"][lite.AVAILABLE] > 0
    assert not list((site / "files").rglob("*.checks.json"))
    for path in served:
        assert lite.leak_failures(json.loads(path.read_text()), path.name) == []

"""The scaffolder, on a generated curriculum as well as on the seed manifest.

A scaffold is the contract between the curriculum and every consumer downstream: it must
be valid nbformat, carry all 8 rubric sections (docs/notebook-rubric.md), and report
🔴 scaffold through nbstatus.py so the gate skips grading it until an author fills it.

Nothing here writes into the real library: `PRAXIS_SUBJECTS_DIR` relocates generated
subjects and `curriculum.NOTEBOOKS_DIR` is repointed for the seed-domain cases, so
tests/test_notebooks.py never sees a notebook this file created.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import curriculum  # noqa: E402
import scaffold_notebooks  # noqa: E402
from curriculum import (  # noqa: E402
    Domain,
    Topic,
    save_subject,
    subject_from_dict,
    subjects_dir,
)
from nbstatus import BADGE, notebook_status  # noqa: E402
from scaffold_notebooks import (  # noqa: E402
    scaffold_domain,
    scaffold_notebook,
    scaffold_subject,
)

# The 8 sections tests/test_notebooks.py grades a finished notebook against.
RUBRIC_SECTIONS = (
    "What & Why",
    "Mental Model",
    "Key Concepts",
    "Setup",
    "Worked Examples",
    "Gotchas",
    "When to Use",
    "Resources",
)

CURRICULUM = {
    "title": "Celestial Navigation",
    "blurb": "Fix a position at sea with a sextant and a clock.",
    "modules": [
        {
            "title": "The Sky",
            "blurb": "What you are actually measuring.",
            "topics": [
                {"title": "The Celestial Sphere"},
                {"title": "Reading a Sextant", "runnable": False, "note": "needs a sextant"},
            ],
        },
        {
            "title": "Sight Reduction",
            "topics": [{"title": "The Intercept Method", "slug": "intercept-method"}],
        },
    ],
}


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    """Generated subjects land in a temp dir — never the developer's notebooks/."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def subject():
    """A curriculum as the generator would hand it over: persisted, not yet scaffolded."""
    subj = subject_from_dict(CURRICULUM, goal="learn to navigate by the stars")
    save_subject(subj)
    return subj


def _text(nb: dict) -> str:
    return "".join("".join(c.get("source", [])) for c in nb.get("cells", []))


# --- scaffolding a generated subject ---------------------------------------


def test_scaffolding_a_generated_subject_writes_a_notebook_per_topic(subject, subjects_root):
    created, skipped = scaffold_subject(subject)

    assert (created, skipped) == (3, 0)
    assert sorted(p.relative_to(subjects_root).as_posix()
                  for p in subjects_root.rglob("*.ipynb")) == [
        "celestial-navigation/01-the-sky/reading-a-sextant.ipynb",
        "celestial-navigation/01-the-sky/the-celestial-sphere.ipynb",
        "celestial-navigation/02-sight-reduction/intercept-method.ipynb",
    ]
    # The curriculum stays where it was, beside its modules.
    assert subject.path.is_file()


def test_every_scaffold_is_valid_and_reports_red(subject, subjects_root):
    scaffold_subject(subject)

    for path in sorted(subjects_root.rglob("*.ipynb")):
        nbformat.read(str(path), as_version=4)  # raises if the notebook is malformed
        status, metrics = notebook_status(path)
        assert status == "scaffold", path
        assert BADGE[status] == "🔴"
        assert metrics["cells"] >= 9


def test_a_scaffold_carries_all_eight_rubric_sections(subject, subjects_root):
    scaffold_subject(subject)
    nb = json.loads(
        (subjects_root / "celestial-navigation" / "01-the-sky"
         / "the-celestial-sphere.ipynb").read_text()
    )
    text = _text(nb)

    missing = [s for s in RUBRIC_SECTIONS if s.lower() not in text.lower()]
    assert not missing, f"scaffold is missing rubric sections: {missing}"
    assert "The Celestial Sphere" in text
    assert "The Sky" in text  # the module it belongs to
    assert nb["metadata"]["praxis"] == {
        "status": "scaffold",
        "domain": "subjects/celestial-navigation/01-the-sky",
        "slug": "the-celestial-sphere",
        "runnable": True,
        "recommended": False,
        "note": "",
    }


def test_a_conceptual_topic_scaffolds_without_code_cells(subject, subjects_root):
    scaffold_subject(subject)
    nb = json.loads(
        (subjects_root / "celestial-navigation" / "01-the-sky"
         / "reading-a-sextant.ipynb").read_text()
    )

    assert [c for c in nb["cells"] if c["cell_type"] == "code"] == []
    assert nb["metadata"]["praxis"]["runnable"] is False
    assert "needs a sextant" in _text(nb)
    assert "isn't Python-runnable" in _text(nb)


def test_a_runnable_topic_scaffolds_with_code_cells(subject, subjects_root):
    scaffold_subject(subject)
    nb = json.loads(
        (subjects_root / "celestial-navigation" / "02-sight-reduction"
         / "intercept-method.ipynb").read_text()
    )

    assert len([c for c in nb["cells"] if c["cell_type"] == "code"]) >= 3


def test_the_rubric_link_resolves_from_where_the_notebook_lives(subject):
    """A subject's module is three levels under notebooks/, not one like a seed domain."""
    module = subject.modules[0]
    nb = scaffold_notebook(module, module.topics[0])
    notebooks_root = subjects_dir().parent  # tmp stand-in for the repo's notebooks/

    link = "../../../../docs/notebook-rubric.md"
    assert link in _text(nb)
    # Relative to the notebook's own directory, that lands beside notebooks/ — which in
    # the real checkout is the rubric this scaffold tells its author to fill to.
    assert (notebooks_root / module.dir / link).resolve() == (
        notebooks_root.parent / "docs" / "notebook-rubric.md"
    )
    assert (ROOT / "docs" / "notebook-rubric.md").is_file()


# --- idempotence -----------------------------------------------------------


def test_rescaffolding_never_clobbers_a_filled_notebook(subject, subjects_root):
    scaffold_subject(subject)
    filled = subjects_root / "celestial-navigation" / "01-the-sky" / "the-celestial-sphere.ipynb"
    filled.write_text(json.dumps({
        "cells": [{"cell_type": "markdown", "id": "x", "metadata": {},
                   "source": ["# The Celestial Sphere\n\nReal content, written by hand."]}],
        "metadata": {"praxis": {"status": "complete", "slug": "the-celestial-sphere"}},
        "nbformat": 4, "nbformat_minor": 5,
    }))
    before = filled.read_text()

    assert scaffold_subject(subject) == (0, 3)
    assert filled.read_text() == before

    # A topic added to the curriculum later is still scaffolded, the rest left alone.
    grown = curriculum.Subject(
        slug=subject.slug,
        title=subject.title,
        modules=(
            Domain(dir=subject.modules[0].dir, title="The Sky", blurb="",
                   topics=subject.modules[0].topics + (Topic("star-catalogues", "Star Catalogues"),),
                   source="subject"),
            *subject.modules[1:],
        ),
    )
    assert scaffold_subject(grown) == (1, 3)
    assert filled.read_text() == before
    assert (filled.parent / "star-catalogues.ipynb").is_file()


# --- the seed manifest still scaffolds the same way ------------------------


def test_a_seed_domain_scaffolds_into_the_notebooks_root(monkeypatch, tmp_path):
    """Same code path as a subject; only domain_path() differs."""
    monkeypatch.setattr(curriculum, "NOTEBOOKS_DIR", tmp_path / "notebooks")
    domain = curriculum.DOMAINS[0]

    created, skipped = scaffold_domain(domain)

    assert (created, skipped) == (len(domain.topics), 0)
    written = tmp_path / "notebooks" / domain.dir / f"{domain.topics[0].slug}.ipynb"
    assert notebook_status(written)[0] == "scaffold"
    assert "../../docs/notebook-rubric.md" in _text(json.loads(written.read_text()))
    assert scaffold_domain(domain) == (0, len(domain.topics))


def test_the_filesystem_domain_is_never_scaffolded(monkeypatch, tmp_path):
    """Domain 11's topics ARE its files — scaffolding it would invent notebooks."""
    monkeypatch.setattr(curriculum, "NOTEBOOKS_DIR", tmp_path / "notebooks")
    legacy = next(d for d in curriculum.DOMAINS if d.source == "filesystem")

    assert scaffold_domain(legacy) == (0, 0)
    assert not (tmp_path / "notebooks").exists()


def test_scaffold_sweeps_the_seed_manifest_and_every_defined_subject(
    monkeypatch, tmp_path, subject, capsys
):
    monkeypatch.setattr(curriculum, "NOTEBOOKS_DIR", tmp_path / "notebooks")
    seed_topics = sum(len(d.topics) for d in curriculum.DOMAINS)

    created, skipped = scaffold_notebooks.scaffold()

    assert (created, skipped) == (seed_topics + subject.n_topics, 0)
    assert "created" in capsys.readouterr().out
    assert scaffold_notebooks.scaffold(subjects=False) == (0, seed_topics)


def test_cli_scaffolds_one_named_subject(subject, subjects_root, capsys):
    assert scaffold_notebooks.main(["--subject", subject.slug]) == 0
    assert len(list(subjects_root.rglob("*.ipynb"))) == subject.n_topics
    assert "created 3" in capsys.readouterr().out

    assert scaffold_notebooks.main(["--subject", "never-defined"]) == 1
    assert scaffold_notebooks.main(["--subject"]) == 2

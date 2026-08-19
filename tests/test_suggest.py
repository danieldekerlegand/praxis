"""A gap becomes a subject the shipped pipeline builds — and nothing else does.

Like band 76's suite, every suggestion here is taken against the real index
(`praxis.library_index`), because the claim is about the *shipped* library: a proposal
survives only if 245 real notebooks say nothing that is it. A fixture corpus would let
this pass while the product suggested a re-tutorial of something on disk.

What is asserted rather than described:

  1. a missing or partial requirement becomes a proposed subject carrying the three
     things band 78 needs — a goal string, its source requirement, and the rationale;
  2. that goal string is *the* input the shipped generator already takes:
     `curriculum_gen.generate_curriculum` consumes it with no new constructor and the
     resulting `Subject` records it as the goal a user typed;
  3. a suggestion never invents its reason — the rationale opens with band 76's own
     sentence and the evidence is band 76's citations, real notebooks off the index;
  4. a `partial` is scoped to the uncovered part: the goal names the adjacent notebook
     it must start past;
  5. no model is reached — a fresh interpreter with no key configured suggests without
     importing `praxis.llm`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import gap, library_index as lib, suggest  # noqa: E402
from praxis.curriculum_gen import generate_curriculum  # noqa: E402
from praxis.suggest import SuggestError  # noqa: E402

from tests.test_curriculum_gen import CURRICULUM, FakeClient  # noqa: E402


@pytest.fixture(scope="module")
def index():
    return lib.build_index()


#: The same posting shape band 76 classifies: MLflow is a notebook, Kubernetes is only
#: adjacent (*Kubernetes Jobsets*), Terraform and incident response are outside the corpus.
REQUIREMENTS = [
    {"name": "MLflow", "kind": "tool", "importance": "required",
     "evidence": "Experience with MLflow for experiment tracking."},
    {"name": "Kubernetes", "kind": "tool", "importance": "required",
     "evidence": "Deep Kubernetes experience: you have debugged a CNI, not just applied YAML."},
    {"name": "Terraform", "kind": "tool", "importance": "preferred", "note": "5+ years",
     "evidence": "Terraform or another IaC tool is a plus."},
    {"name": "Incident response", "kind": "competency", "importance": "required",
     "evidence": "You own incident response for the services you ship."},
]


@pytest.fixture(scope="module")
def analysis(index):
    return gap.analyze(REQUIREMENTS, index=index)


@pytest.fixture(scope="module")
def suggested(analysis):
    return suggest.suggest(analysis)


# --- a gap becomes a proposed subject ----------------------------------------


def test_every_gap_becomes_a_proposed_subject(suggested):
    assert [s["title"] for s in suggested["suggestions"]] == [
        "Kubernetes", "Terraform", "Incident response",
    ]
    assert suggested["count"] == 3
    assert suggested["counts"] == {"missing": 2, "partial": 1}


def test_a_proposal_carries_a_goal_a_source_requirement_and_a_rationale(suggested):
    for row in suggested["suggestions"]:
        assert row["goal"].strip() and row["goal"].startswith("I want to")
        assert row["rationale"].strip()
        assert row["coverage"] in suggest.SUGGESTABLE
        source = row["requirement"]
        assert source["name"] == row["title"]
        assert source["kind"] and source["importance"]
        # the posting's own words survive band 76 folding its citations onto the row
        assert source["evidence"] in [r["evidence"] for r in REQUIREMENTS]
        assert row["id"] == source["id"]


def test_the_goal_says_what_the_posting_asked_and_how_hard(suggested):
    (terraform,) = [s for s in suggested["suggestions"] if s["title"] == "Terraform"]
    assert "hands-on with Terraform" in terraform["goal"]          # kind: tool
    assert "credible about it" in terraform["goal"]                # importance: preferred
    assert "lists it as preferred (5+ years)" in terraform["goal"]  # the posting's note
    assert "Terraform or another IaC tool is a plus." in terraform["goal"]

    (incident,) = [s for s in suggested["suggestions"] if s["title"] == "Incident response"]
    assert "get good at Incident response" in incident["goal"]     # kind: competency
    assert "use it in the job" in incident["goal"]                 # importance: required


def test_the_document_records_the_library_the_suggestions_were_taken_against(
    suggested, analysis
):
    assert suggested["version"] == suggest.SUGGEST_VERSION
    assert suggested["library"] == analysis["library"]
    assert suggested["count"] == sum(suggested["counts"].values())
    assert suggested["suggested"]


# --- the shipped generator takes it, unchanged --------------------------------


def test_a_suggested_goal_is_what_generate_curriculum_already_takes(suggested):
    """The whole point of the band: an accepted suggestion is a hand-typed subject.

    No new constructor — the goal string goes into the shipped generator, reaches the
    model in the shipped prompt, and comes back as a `Subject` recording that goal.
    """
    (terraform,) = [s for s in suggested["suggestions"] if s["title"] == "Terraform"]
    client = FakeClient(json.dumps(CURRICULUM))

    subject = generate_curriculum(terraform["goal"], client=client, slug=terraform["id"])

    assert subject.goal == terraform["goal"]
    assert subject.slug == "terraform"
    assert terraform["goal"] in client.calls[0]["prompt"]
    assert subject.modules and subject.modules[0].topics


# --- the reason is band 76's, not this band's ---------------------------------


def test_the_rationale_is_the_gap_analysis_sentence(suggested, analysis):
    for row in suggested["suggestions"]:
        (source,) = [r for r in analysis["requirements"] if r["name"] == row["title"]]
        assert row["rationale"].startswith(source["why"])
        assert row["evidence"] == source["evidence"]


def test_a_partial_is_scoped_to_the_part_the_library_does_not_cover(suggested):
    (k8s,) = [s for s in suggested["suggestions"] if s["title"] == "Kubernetes"]
    assert k8s["coverage"] == "partial"
    assert "Kubernetes Jobsets" in k8s["goal"]
    assert "rather than covering it again" in k8s["goal"]
    assert "start past that material, not repeat it" in k8s["rationale"]
    assert [c["rel"] for c in k8s["evidence"]][0].endswith(".ipynb")


def test_a_missing_requirement_cites_nothing_because_there_is_nothing_to_cite(suggested):
    (terraform,) = [s for s in suggested["suggestions"] if s["title"] == "Terraform"]
    assert terraform["evidence"] == []
    assert "nothing in the library addresses Terraform" in terraform["rationale"]


# --- what is not suggestable --------------------------------------------------


def test_a_covered_requirement_is_not_a_candidate(analysis):
    (mlflow,) = [r for r in analysis["requirements"] if r["name"] == "MLflow"]
    assert suggest.suggest_requirement(mlflow) is None


def test_an_unclassified_requirement_list_is_classified_on_the_way_through(index):
    doc = suggest.suggest(REQUIREMENTS, index=index)
    assert [s["title"] for s in doc["suggestions"]] == [
        "Kubernetes", "Terraform", "Incident response",
    ]


@pytest.mark.parametrize("payload", [None, {}, [], {"requirements": []}, 42])
def test_there_is_nothing_to_suggest_without_requirements(payload, index):
    with pytest.raises(SuggestError):
        suggest.suggest(payload, index=index)


def test_a_row_with_no_gap_analysis_cannot_be_given_a_rationale():
    with pytest.raises(SuggestError, match="no gap analysis"):
        suggest.suggest_requirement({"name": "Terraform", "coverage": "missing"})


# --- no model -----------------------------------------------------------------


SUGGEST_IT = """
import json, sys
sys.path.insert(0, {root!r})
from praxis import suggest

doc = suggest.suggest([
    {{"name": "MLflow", "kind": "tool"}},
    {{"name": "Kubernetes", "kind": "tool"}},
    {{"name": "Terraform", "kind": "tool"}},
])
print(json.dumps({{
    "titles": [s["title"] for s in doc["suggestions"]],
    "goals": [bool(s["goal"]) for s in doc["suggestions"]],
    "llm_imported": "praxis.llm" in sys.modules,
}}))
"""


def test_suggesting_reaches_no_model_and_needs_no_key(tmp_path):
    """Band 75 spent the funnel's model call; the next is the constructor's, after a
    human accepts. Suggesting in a fresh interpreter with nothing configured must work."""
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        [sys.executable, "-c", SUGGEST_IT.format(root=str(ROOT))],
        capture_output=True, text=True, cwd=str(home),
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )
    assert proc.returncode == 0, proc.stderr
    restarted = json.loads(proc.stdout)
    assert restarted["titles"] == ["Kubernetes", "Terraform"]
    assert restarted["goals"] == [True, True]
    assert restarted["llm_imported"] is False

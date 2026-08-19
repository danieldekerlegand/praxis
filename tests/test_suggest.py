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
  5. **restraint**: a proposal is re-asked of the *live* index before it survives, so a
     requirement a notebook, a `recommended` neighbour or a whole domain answers for
     yields no suggestion at all — even when the analysis snapshot it arrived on says
     otherwise — and a posting that asks for one thing three ways gets one tutorial;
  6. no model is reached — a fresh interpreter with no key configured suggests without
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

import curriculum  # noqa: E402
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
    assert suggested["droppedCount"] == sum(suggested["dropCounts"].values())
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


def test_a_partial_is_scoped_to_the_part_the_library_does_not_cover(suggested, index):
    (k8s,) = [s for s in suggested["suggestions"] if s["title"] == "Kubernetes"]
    assert k8s["coverage"] == "partial"
    # it survived the dedup pass because nothing shipped *is* it — the adjacency the
    # goal is told to start past is not a reason to teach that notebook again
    assert index.lookup("Kubernetes") == ()
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


# --- restraint: dedup against the shipped library -----------------------------


def stale_analysis(*names: str, coverage: str = "missing") -> dict:
    """Band 76's document as it would read if taken *before* the library had these.

    The snapshot is wrong on purpose, which is the only way to test the dedup pass at
    all: every requirement here already carries the verdict that would let it through,
    so a suggestion surviving means the library was never re-asked.
    """
    return {
        "jd": "stale-posting",
        "title": "Stale Posting",
        "requirements": [
            {
                "name": name,
                "kind": "tool",
                "importance": "required",
                "quote": f"You will use {name} daily.",
                "coverage": coverage,
                "why": f"nothing in the library addresses {name}",
                "evidence": [],
            }
            for name in names
        ],
    }


def test_a_requirement_a_shipped_notebook_is_yields_no_suggestion(index):
    doc = suggest.suggest(stale_analysis("MLflow"), index=index)

    assert doc["suggestions"] == [] and doc["count"] == 0
    (dropped,) = doc["dropped"]
    assert dropped["reason"] == "shipped"
    assert [c["rel"] for c in dropped["evidence"]] == ["02-ai-ml-tooling/mlflow.ipynb"]
    assert "the library already teaches MLflow" in dropped["why"]


def test_a_requirement_a_recommended_neighbour_is_yields_no_suggestion(index):
    """§2 of gap-analysis.md: a recommended topic is already scaffolded in
    `curriculum.py`, so building a second tutorial for it is the redundancy the whole
    funnel exists to avoid. It counts as library, not as a gap."""
    doc = suggest.suggest(stale_analysis("Optuna"), index=index)

    assert doc["suggestions"] == [] and doc["count"] == 0
    (dropped,) = doc["dropped"]
    assert dropped["reason"] == "recommended"
    assert all(cite["recommended"] for cite in dropped["evidence"])
    assert "already scaffolded" in dropped["why"]


def test_a_requirement_a_whole_domain_is_named_for_yields_no_suggestion(index):
    doc = suggest.suggest(stale_analysis("Model Evaluation"), index=index)

    assert doc["suggestions"] == [] and doc["count"] == 0
    (dropped,) = doc["dropped"]
    assert dropped["reason"] == "domain"
    assert len(dropped["evidence"]) > 1
    assert "a whole domain" in dropped["why"]


def test_a_genuinely_missing_requirement_survives_the_same_pass(index):
    doc = suggest.suggest(
        stale_analysis("MLflow", "Terraform", "Optuna", "Model Evaluation"), index=index
    )

    assert [s["title"] for s in doc["suggestions"]] == ["Terraform"]
    assert [d["reason"] for d in doc["dropped"]] == ["shipped", "recommended", "domain"]
    assert doc["count"] == 1 and doc["droppedCount"] == 3
    assert doc["dropCounts"] == {
        "shipped": 1, "recommended": 1, "domain": 1, "duplicate": 0,
    }


def test_one_ask_spelled_three_ways_is_one_tutorial(index):
    """A posting repeats itself; a curriculum should not. The earliest spelling wins,
    because the posting's own order is the only priority either band has."""
    doc = suggest.suggest(
        stale_analysis(
            "Kubernetes", "Advanced Kubernetes experience", "Kubernetes operators"
        ),
        index=index,
    )

    assert [s["title"] for s in doc["suggestions"]] == ["Kubernetes"]
    assert [d["title"] for d in doc["dropped"]] == [
        "Advanced Kubernetes experience", "Kubernetes operators",
    ]
    assert {d["reason"] for d in doc["dropped"]} == {"duplicate"}
    assert {d["duplicateOf"] for d in doc["dropped"]} == {"kubernetes"}


def test_two_genuinely_different_asks_are_not_collapsed(index):
    doc = suggest.suggest(stale_analysis("Terraform", "Incident response"), index=index)

    assert [s["title"] for s in doc["suggestions"]] == ["Terraform", "Incident response"]
    assert doc["dropped"] == []


def test_the_dedup_is_against_the_live_index_not_the_analysis_snapshot(monkeypatch):
    """The anti-fabrication claim of the band, and the reason `dedupe` re-classifies
    rather than reading the verdict it was handed: a topic scaffolded *since* the
    analysis was taken still stops the re-tutorial."""
    analysis = stale_analysis("Wombat-Oriented Design")
    assert suggest.suggest(analysis, index=lib.library_index(refresh=True))["count"] == 1

    extra = curriculum.Domain(
        "99-brand-new", "Brand New", "added at runtime",
        (curriculum.T("wombat-oriented-design", "Wombat-Oriented Design"),),
    )
    monkeypatch.setattr(curriculum, "DOMAINS", curriculum.DOMAINS + [extra])
    lib.library_index(refresh=True)
    try:
        doc = suggest.suggest(analysis)  # no index of its own: the live library

        assert doc["suggestions"] == [] and doc["count"] == 0
        (dropped,) = doc["dropped"]
        assert dropped["reason"] == "shipped"
        assert dropped["evidence"][0]["rel"] == (
            "99-brand-new/wombat-oriented-design.ipynb"
        )
    finally:
        monkeypatch.undo()
        lib.library_index(refresh=True)  # leave the cache holding the real library


def test_a_drop_is_recorded_whole_so_a_reviewer_can_undo_it(index):
    """Restraint is shown, not silent: band 78 gets the goal it would have offered and
    the sentence saying why it did not."""
    doc = suggest.suggest(stale_analysis("MLflow"), index=index)

    (dropped,) = doc["dropped"]
    assert dropped["title"] == "MLflow"
    assert dropped["goal"].startswith("I want to")
    assert dropped["requirement"]["name"] == "MLflow"
    assert dropped["rationale"]
    assert dropped["reason"] in suggest.DROP_REASONS


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

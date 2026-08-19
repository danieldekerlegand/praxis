"""Covered, partial, missing — against the library that actually shipped.

Every classification here is taken against the real index (`praxis.library_index`), not
a fixture corpus, because the claim the band makes is about the *shipped* library: a
requirement is missing only if 245 real notebooks say nothing about it. A stub corpus
would let this suite pass while the product fabricated gaps.

Three things are asserted rather than described:

  1. the three-way verdict, on one mixed list, each verdict carrying evidence that names
     notebooks on disk;
  2. `covered` is never earned by adjacency, however high it scores — *Kubernetes
     Jobsets* accounts for every word of "Kubernetes" and is not a Kubernetes tutorial,
     and over-calling `covered` is what silently drops a requirement a learner needs;
  3. no model is reached: the verdict is a string match, so a fresh interpreter with no
     key configured classifies a list without importing `praxis.llm`.
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
from praxis import gap, jd, jd_extract, library_index as lib  # noqa: E402
from praxis.gap import GapError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jd"


@pytest.fixture(scope="module")
def index():
    return lib.build_index()


#: One posting's worth of requirements, chosen so the library answers all three ways:
#: MLflow and Prompt Engineering are notebooks, JAX & Flax is a `recommended` neighbour,
#: Kubernetes is only adjacent, and Terraform / incident response are outside the corpus.
MIXED = [
    {"name": "MLflow", "kind": "tool", "importance": "required"},
    {"name": "JAX & Flax", "kind": "tool", "importance": "preferred"},
    {"name": "Kubernetes", "kind": "tool", "importance": "required"},
    {"name": "Terraform", "kind": "tool", "importance": "required"},
    {"name": "Incident response", "kind": "competency", "importance": "required"},
]


# --- the three-way verdict, with evidence ------------------------------------


@pytest.fixture(scope="module")
def mixed(index):
    return gap.analyze(MIXED, index=index)


def test_a_mixed_list_classifies_all_three_ways(mixed):
    verdicts = {r["name"]: r["coverage"] for r in mixed["requirements"]}
    assert verdicts == {
        "MLflow": "covered",
        "JAX & Flax": "covered",
        "Kubernetes": "partial",
        "Terraform": "missing",
        "Incident response": "missing",
    }
    assert mixed["counts"] == {"covered": 2, "partial": 1, "missing": 2}


def test_a_covered_requirement_cites_the_notebook_that_teaches_it(mixed):
    (row,) = [r for r in mixed["requirements"] if r["name"] == "MLflow"]
    (cite,) = row["evidence"]
    assert cite["rel"] == "02-ai-ml-tooling/mlflow.ipynb"
    assert cite["domain"] == "02-ai-ml-tooling" and cite["domainTitle"] == "AI/ML Tooling"
    assert cite["match"] == "exact" and cite["score"] == 1.0
    assert "MLflow" in row["why"]


def test_a_partial_requirement_cites_what_is_adjacent_to_it(mixed):
    (row,) = [r for r in mixed["requirements"] if r["name"] == "Kubernetes"]
    assert row["evidence"], "a partial verdict with no evidence is not a partial verdict"
    assert [c["rel"] for c in row["evidence"]] == [
        "11-devops-mlops-infra/job-orchestration-tools/kubernetes-jobsets.ipynb"
    ]
    assert all(c["match"] == "adjacent" for c in row["evidence"])
    assert all(c["score"] >= gap.PARTIAL_FLOOR for c in row["evidence"])
    assert "Kubernetes Jobsets" in row["why"]


def test_a_missing_requirement_cites_nothing_and_says_so(mixed):
    for name in ("Terraform", "Incident response"):
        (row,) = [r for r in mixed["requirements"] if r["name"] == name]
        assert row["evidence"] == []
        assert row["why"] == f"nothing in the library addresses {name}"


def test_every_piece_of_evidence_names_a_notebook_on_disk(mixed):
    cited = [c["rel"] for r in mixed["requirements"] for c in r["evidence"]]
    assert cited
    assert [rel for rel in cited if not (curriculum.NOTEBOOKS_DIR / rel).is_file()] == []


# --- what counts as covered ---------------------------------------------------


def test_a_recommended_neighbour_counts_as_covered(mixed, index):
    """It is already scaffolded (gap-analysis.md §2) — re-tutorialing it is the
    redundancy this funnel exists to avoid — but the verdict says it needs filling."""
    (row,) = [r for r in mixed["requirements"] if r["name"] == "JAX & Flax"]
    (cite,) = row["evidence"]
    assert row["coverage"] == "covered"
    assert cite["recommended"] is True
    assert "scaffolded" in row["why"]


def test_adjacency_alone_never_earns_covered(index):
    """*Kubernetes Jobsets* accounts for every word of "Kubernetes" and is still not a
    Kubernetes tutorial. Scoring 1.0 on `related()` must not read as covered."""
    ((topic, score),) = index.related("Kubernetes")
    assert score == 1.0 and topic.rel.endswith("kubernetes-jobsets.ipynb")
    assert gap.classify("Kubernetes", index=index)["coverage"] == "partial"


def test_a_whole_domain_named_for_the_requirement_is_coverage(index):
    verdict = gap.classify("Model Evaluation", index=index)
    assert verdict["coverage"] == "covered"
    assert {c["domain"] for c in verdict["evidence"]} == {"12-model-evaluation"}
    assert all(c["match"] == "domain" for c in verdict["evidence"])
    assert "Model Evaluation" in verdict["why"]


def test_a_one_word_piece_of_a_domain_title_is_not_a_domain(index):
    """"Research" is half of "Data Analysis & Research" and names anything at all — a
    domain is claimed by its whole title or by a piece of it worth more than one word."""
    keys = gap.domain_keys(index)
    assert "data analysis" in keys and "research" not in keys
    assert "interpretability" in keys  # a one-word key, but the whole title


def test_a_phrase_naming_two_notebooks_cites_both(index):
    verdict = gap.classify("vLLM", index=index)
    assert verdict["coverage"] == "covered"
    assert sorted(c["rel"] for c in verdict["evidence"]) == [
        "03-llm-inference-training-optimization/vllm.ipynb",
        "11-devops-mlops-infra/model-serving-libraries/vllm.ipynb",
    ]


@pytest.mark.parametrize("phrase", [
    "Prompt engineering",
    "Hands-on prompt engineering experience",
    "Deep prompt-engineering expertise",
])
def test_the_qualifiers_a_posting_wraps_a_requirement_in_are_dropped(index, phrase):
    verdict = gap.classify(phrase, index=index)
    assert verdict["coverage"] == "covered"
    assert [c["rel"] for c in verdict["evidence"]] == [
        "03-llm-inference-training-optimization/prompt-engineering.ipynb"
    ]


def test_the_phrase_is_tried_as_written_before_it_is_stripped():
    assert gap.phrases("Hands-on Kubernetes experience") == (
        "hand kubernete experience", "kubernete",
    )
    assert gap.phrases("Kubernetes") == ("kubernete",)
    assert gap.phrases("  ") == ()


def test_a_requirement_with_no_name_is_missing_rather_than_an_error(index):
    verdict = gap.classify("", index=index)
    assert verdict == {
        "coverage": "missing",
        "why": "that requirement has no name to match",
        "evidence": [],
    }


def test_a_word_or_two_shared_with_an_unrelated_topic_is_not_a_partial(index):
    """Below the floor a topic shares a word and no subject — reporting that as "we have
    something near this" would bury the real gap."""
    scored = index.related("Salesforce Apex administration and reporting")
    assert all(score < gap.PARTIAL_FLOOR for _, score in scored)
    verdict = gap.classify("Salesforce Apex administration and reporting", index=index)
    assert verdict["coverage"] == "missing" and verdict["evidence"] == []


# --- the document band 77 reads ----------------------------------------------


def test_the_analysis_keeps_every_field_the_extractor_wrote(mixed):
    row = mixed["requirements"][0]
    assert row["kind"] == "tool" and row["importance"] == "required"
    assert [r["name"] for r in mixed["requirements"]] == [r["name"] for r in MIXED]


def test_the_analysis_records_the_library_it_was_taken_against(mixed, index):
    assert mixed["version"] == gap.GAP_VERSION
    assert mixed["library"] == {"domains": len(index.domains), "topics": len(index)}
    assert mixed["count"] == len(MIXED) == sum(mixed["counts"].values())
    assert mixed["coverage"] == list(gap.COVERAGE)


def test_a_band_75_document_can_be_handed_over_whole(index):
    doc = jd.document_from_upload(
        "senior-platform-engineer.txt",
        (FIXTURES / "senior-platform-engineer.txt").read_bytes(),
    )
    requirements = jd_extract.requirements_from_reply({"requirements": [
        {"name": "Kubernetes", "kind": "tool", "evidence": "Deep Kubernetes experience"},
        {"name": "MLflow", "kind": "tool", "evidence": "unused here"},
    ]})
    payload = jd_extract.build_requirements(doc, requirements, model="test-model")

    analysis = gap.analyze(payload, index=index)
    assert analysis["jd"] == doc["id"] and analysis["title"] == doc["title"]
    assert [r["coverage"] for r in analysis["requirements"]] == ["partial", "covered"]


def test_the_gaps_are_what_the_library_does_not_already_teach(mixed):
    assert [r["name"] for r in gap.gaps(mixed)] == [
        "Kubernetes", "Terraform", "Incident response",
    ]


def test_a_bare_phrase_is_a_requirement_too(index):
    (row,) = gap.analyze(["MLflow"], index=index)["requirements"]
    assert row["name"] == "MLflow" and row["coverage"] == "covered"


@pytest.mark.parametrize("payload", [None, {}, [], {"requirements": []}, "MLflow"])
def test_there_is_nothing_to_classify_without_a_requirement_list(payload, index):
    with pytest.raises(GapError, match="no requirements to classify"):
        gap.analyze(payload, index=index)


def test_a_requirement_that_is_not_an_object_is_refused(index):
    with pytest.raises(GapError, match="not an object"):
        gap.analyze([42], index=index)


def test_the_index_is_read_live_here_too(monkeypatch):
    """`analyze` with no index of its own goes through `library_index()`, which is the
    curriculum — so a topic added to it is classified as covered, not as a gap."""
    extra = curriculum.Domain(
        "99-brand-new", "Brand New", "added at runtime",
        (curriculum.T("wombat-oriented-design", "Wombat-Oriented Design"),),
    )
    assert gap.classify("Wombat-Oriented Design", index=lib.library_index(refresh=True))[
        "coverage"] == "missing"
    monkeypatch.setattr(curriculum, "DOMAINS", curriculum.DOMAINS + [extra])
    lib.library_index(refresh=True)
    try:
        verdict = gap.classify("Wombat-Oriented Design")
        assert verdict["coverage"] == "covered"
        assert verdict["evidence"][0]["rel"] == "99-brand-new/wombat-oriented-design.ipynb"
    finally:
        monkeypatch.undo()
        lib.library_index(refresh=True)  # leave the cache holding the real library


# --- no model -----------------------------------------------------------------


CLASSIFY_IT = """
import json, sys
sys.path.insert(0, {root!r})
from praxis import gap

analysis = gap.analyze(["MLflow", "Kubernetes", "Terraform"])
print(json.dumps({{
    "coverage": [r["coverage"] for r in analysis["requirements"]],
    "llm_imported": "praxis.llm" in sys.modules,
}}))
"""


def test_classifying_reaches_no_model_and_needs_no_key(tmp_path):
    """The funnel's one model call is band 75's. A gap analysis in a fresh interpreter
    with nothing configured must still produce the same three verdicts."""
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        [sys.executable, "-c", CLASSIFY_IT.format(root=str(ROOT))],
        capture_output=True, text=True, cwd=str(home),
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )
    assert proc.returncode == 0, proc.stderr
    restarted = json.loads(proc.stdout)
    assert restarted["coverage"] == ["covered", "partial", "missing"]
    assert restarted["llm_imported"] is False

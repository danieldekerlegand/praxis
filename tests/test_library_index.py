"""The corpus a JD requirement is diffed against — built live, or it is worthless.

Two claims carry this band, and both are asserted here rather than described:

  1. the index is read out of `curriculum.DOMAINS` at call time, not copied — a topic
     added to the curriculum is in the corpus, and a test that appends one proves it;
  2. what it reads is the library that actually shipped — 14 domains and one entry per
     notebook on disk, counted from the filesystem *and* pinned to a literal, so a
     stale copy or a silently dropped domain fails loudly instead of narrowing the
     corpus (which would read as "the library doesn't teach that" — a fabricated gap).

The rest is the normalizer, and it is tested on both sides at once: a topic title and
the way a posting phrases it must land on the same key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import curriculum  # noqa: E402
from praxis import library_index as lib  # noqa: E402

#: What the shipped library is, as of this commit. A change here is a change to the
#: product's corpus and should be a deliberate edit, not a surprise.
SHIPPED_DOMAINS = 14
SHIPPED_TOPICS = 245
SHIPPED_RECOMMENDED = 90


@pytest.fixture(scope="module")
def index():
    return lib.build_index()


# --- built live from the curriculum ------------------------------------------


def test_the_index_is_the_curriculum_not_a_copy_of_it(index):
    assert [d.dir for d in index.domains] == [d.dir for d in curriculum.DOMAINS]


def test_a_topic_added_to_the_curriculum_is_in_the_corpus(monkeypatch):
    """The anti-drift claim: no hand-copied list could pass this."""
    extra = curriculum.Domain(
        "99-brand-new", "Brand New", "added at runtime",
        (curriculum.T("wombat-oriented-design", "Wombat-Oriented Design"),),
    )
    monkeypatch.setattr(curriculum, "DOMAINS", curriculum.DOMAINS + [extra])

    index = lib.build_index()
    assert len(index) == SHIPPED_TOPICS + 1
    (topic,) = index.lookup("wombat oriented design")
    assert topic.rel == "99-brand-new/wombat-oriented-design.ipynb"
    assert topic.domain_title == "Brand New"


def test_the_counts_are_the_shipped_library(index):
    on_disk = sorted(
        p.relative_to(curriculum.NOTEBOOKS_DIR).as_posix()
        for p in curriculum.NOTEBOOKS_DIR.rglob("*.ipynb")
    )
    assert len(index.domains) == SHIPPED_DOMAINS == len(curriculum.DOMAINS)
    assert len(index) == SHIPPED_TOPICS == len(on_disk)
    assert sorted(t.rel for t in index.topics) == on_disk


def test_every_entry_names_a_notebook_that_exists(index):
    missing = [t.rel for t in index.topics
               if not (curriculum.NOTEBOOKS_DIR / t.rel).is_file()]
    assert missing == []


def test_recommended_neighbours_are_part_of_the_corpus(index):
    """A `recommended` topic is already scaffolded, so it counts as library — that is
    the redundancy this funnel exists to avoid re-tutorialing."""
    recommended = [t for t in index.topics if t.recommended]
    assert len(recommended) == SHIPPED_RECOMMENDED
    (jax,) = index.lookup("JAX & Flax")
    assert jax.recommended is True


def test_the_legacy_domain_enumerates_no_topics_but_is_indexed_anyway(index):
    """Domain 11 is `source="filesystem"` — its notebooks are the only manifest."""
    legacy = curriculum.domain_by_dir("11-devops-mlops-infra")
    assert legacy.source == "filesystem" and legacy.topics == ()
    rows = [t for t in index.topics if t.domain == legacy.dir]
    assert len(rows) == 65
    assert any("/" in t.rel.split("/", 1)[1] for t in rows)  # nested ones too


# --- one normalizer, used on both sides --------------------------------------


@pytest.mark.parametrize("phrase", [
    "scikit-learn", "Scikit Learn", "  SCIKIT-LEARN!  ", "sklearn", "scikit-learns",
])
def test_a_topic_is_found_however_the_posting_spells_it(index, phrase):
    (topic,) = index.lookup(phrase)
    assert topic.rel == "02-ai-ml-tooling/scikit-learn.ipynb"


@pytest.mark.parametrize("phrase, rel", [
    ("Model Context Protocol", "04-agentic-ai/model-context-protocol.ipynb"),
    ("MCP", "04-agentic-ai/model-context-protocol.ipynb"),
    ("Answer Set Programming", "01-symbolic-ai-logic/answer-set-programming.ipynb"),
    ("clingo", "01-symbolic-ai-logic/answer-set-programming.ipynb"),
    ("ASP", "01-symbolic-ai-logic/answer-set-programming.ipynb"),
    ("chain of thought", "03-llm-inference-training-optimization/chain-of-thought.ipynb"),
])
def test_the_names_inside_a_title_are_keys_too(index, phrase, rel):
    assert rel in [t.rel for t in index.lookup(phrase)]


def test_an_alias_and_its_expansion_are_one_key():
    assert lib.match_key("K8s") == lib.match_key("Kubernetes")
    assert lib.match_key("LLMs") == lib.match_key("large language models")
    assert lib.match_key("AWS") == lib.match_key("Amazon Web Services")


def test_a_short_name_is_not_folded_as_a_plural(index):
    """"VITS" is a TTS model; "ViT" is a vision transformer, and its title carries "vit"
    as a key. Folding the one onto the other would report the wrong notebook as cover."""
    assert lib.match_key("VITS") != lib.match_key("ViT")
    (vits,) = index.lookup("VITS")
    assert vits.rel == "05-speech-audio/vits.ipynb"
    assert "08-architectures/vision-transformer.ipynb" in [t.rel for t in index.lookup("ViT")]


def test_nothing_in_the_library_is_not_matched(index):
    assert index.lookup("Rust") == ()
    assert index.lookup("Salesforce administration") == ()


# --- adjacency, for the classifier one band up -------------------------------


def test_related_ranks_the_nearest_topic_first(index):
    scored = index.related("retrieval augmented generation pipelines")
    assert scored
    top, score = scored[0]
    assert top.rel == "03-llm-inference-training-optimization/rag.ipynb"
    assert 0 < score <= 1


def test_related_is_empty_for_a_phrase_the_library_shares_no_words_with(index):
    assert index.related("Salesforce Apex administration") == []


def test_a_common_word_counts_for_less_than_a_rare_one(index):
    assert index.idf("clingo") > index.idf("model")


def test_the_cached_index_can_be_refreshed(monkeypatch):
    first = lib.library_index(refresh=True)
    assert lib.library_index() is first
    monkeypatch.setattr(curriculum, "DOMAINS", curriculum.DOMAINS[:1])
    assert len(lib.library_index(refresh=True)) == len(curriculum.DOMAINS[0].topics)
    lib.library_index(refresh=True)  # leave the process cache holding the real library

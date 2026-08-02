"""The curriculum model: a user-defined subject is the same shape as a seed domain.

Everything downstream (scaffolder, launcher, gate) consumes `Domain`/`Topic`, so a
generated subject must normalize into exactly those — with slugs that are safe as
filenames, unique inside a curriculum, and stable across a save/load round trip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import curriculum  # noqa: E402
from curriculum import (  # noqa: E402
    DOMAINS,
    CurriculumError,
    all_subjects,
    load_subject,
    save_subject,
    seed_subject,
    slugify,
    subject_from_dict,
    subjects_dir,
)
from praxis import storage  # noqa: E402

PAYLOAD = {
    "title": "Embedded Rust",
    "blurb": "Write firmware for a Cortex-M board in Rust.",
    "modules": [
        {
            "title": "Foundations",
            "blurb": "The language features firmware leans on.",
            "topics": [
                {"title": "Ownership and Borrowing", "slug": "ownership-and-borrowing"},
                {"title": "no_std Rust", "runnable": False, "note": "needs hardware"},
            ],
        },
        {
            "title": "Talking to Hardware",
            "topics": [{"title": "GPIO and the HAL"}],
        },
    ],
}


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path):
    """Never read or write the developer's real notebooks/subjects/."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "subjects"))
    return tmp_path / "subjects"


def test_slugify_makes_a_safe_file_stem():
    assert slugify("Ownership & Borrowing!") == "ownership-borrowing"
    assert slugify("  C++ / STL  ") == "c-stl"
    assert slugify("...", fallback="module-3") == "module-3"
    assert len(slugify("x" * 200)) <= 60


def test_a_generated_payload_becomes_domains_and_topics():
    subject = subject_from_dict(PAYLOAD, goal="I want to write STM32 firmware")

    assert subject.slug == "embedded-rust"
    assert subject.goal == "I want to write STM32 firmware"
    assert subject.source == "generated"
    assert subject.created  # stamped on the way in
    assert [m.title for m in subject.modules] == ["Foundations", "Talking to Hardware"]
    assert [m.dir for m in subject.modules] == [
        "subjects/embedded-rust/01-foundations",
        "subjects/embedded-rust/02-talking-to-hardware",
    ]
    # Modules are Domains, so the launcher and scaffolder need no special case.
    assert all(m.source == "subject" for m in subject.modules)
    assert subject.n_topics == 3

    nostd = subject.modules[0].topics[1]
    assert nostd.slug == "no-std-rust"  # derived from the title when absent
    assert nostd.runnable is False and nostd.note == "needs hardware"
    assert subject.modules[0].topics[0].runnable is True  # defaults to runnable


def test_topics_that_slugify_alike_never_share_a_notebook():
    payload = {
        "title": "Dup",
        "modules": [{"title": "M", "topics": [{"title": "K-means"}, {"title": "k means"}]}],
    }
    slugs = [t.slug for t in subject_from_dict(payload).modules[0].topics]
    assert slugs == ["k-means", "k-means-2"]


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not an object", "must be an object"),
        ({"title": "T"}, "no modules"),
        ({"title": "T", "modules": []}, "no modules"),
        ({"title": "T", "modules": [{"title": "M", "topics": []}]}, "no topics"),
        ({"title": "T", "modules": [{"title": "M", "topics": [{}]}]}, "missing its title"),
        ({"modules": [{"title": "M", "topics": [{"title": "x"}]}]}, "missing its title"),
    ],
)
def test_a_payload_the_scaffolder_could_not_use_is_rejected(payload, message):
    with pytest.raises(CurriculumError, match=message):
        subject_from_dict(payload)


def test_a_stored_module_dir_may_not_escape_the_subject():
    payload = {
        "title": "Escape",
        "modules": [
            {"title": "M", "dir": "subjects/escape/../../etc", "topics": [{"title": "x"}]}
        ],
    }
    with pytest.raises(CurriculumError, match="escapes"):
        subject_from_dict(payload)


def test_save_load_round_trip_keeps_the_curriculum_identical(subjects_root):
    subject = subject_from_dict(PAYLOAD, goal="firmware", model="claude-opus-5")
    path = save_subject(subject)

    assert path == subjects_root / "embedded-rust" / "curriculum.json"
    assert json.loads(path.read_text())["model"] == "claude-opus-5"
    assert load_subject("embedded-rust") == subject


def test_renaming_a_subject_title_cannot_orphan_its_notebooks(subjects_root):
    """Module dirs are persisted, so a reload never re-derives a different path."""
    save_subject(subject_from_dict(PAYLOAD))
    stored = json.loads((subjects_root / "embedded-rust" / "curriculum.json").read_text())
    stored["title"] = "Bare-Metal Rust"
    (subjects_root / "embedded-rust" / "curriculum.json").write_text(json.dumps(stored))

    reloaded = load_subject("embedded-rust")
    assert reloaded.title == "Bare-Metal Rust"
    assert reloaded.modules[0].dir == "subjects/embedded-rust/01-foundations"


def test_all_subjects_lists_newest_first_and_survives_a_broken_file(subjects_root):
    assert all_subjects() == []

    save_subject(subject_from_dict({**PAYLOAD, "created": "2026-01-01T00:00:00+00:00"}))
    save_subject(
        subject_from_dict(
            {**PAYLOAD, "title": "Ancient Greek", "created": "2025-01-01T00:00:00+00:00"}
        )
    )
    (subjects_root / "broken").mkdir()
    (subjects_root / "broken" / "curriculum.json").write_text("{ not json")

    assert [s.slug for s in all_subjects()] == ["embedded-rust", "ancient-greek"]


def test_missing_subject_is_an_error_not_a_crash():
    with pytest.raises(CurriculumError, match="no subject"):
        load_subject("never-defined")


def test_subjects_dir_follows_the_active_storage_backend(monkeypatch, tmp_path, app_dir):
    """A user's subjects are their data: they live on the storage backend, not in the
    shipped library. `PRAXIS_SUBJECTS_DIR` still moves that one leaf."""
    monkeypatch.delenv("PRAXIS_SUBJECTS_DIR", raising=False)
    assert subjects_dir() == storage.subjects_dir() == app_dir / "data" / "subjects"
    assert subjects_dir() != curriculum.NOTEBOOKS_DIR / "subjects"
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path))
    assert subjects_dir() == tmp_path


def test_the_seed_library_is_itself_a_subject():
    """The built-ins stay — as one curriculum among others, not as a special case."""
    seed = seed_subject()
    assert seed.source == "seed"
    assert seed.modules == tuple(DOMAINS)
    assert seed.n_topics == sum(len(d.topics) for d in DOMAINS)
    assert curriculum.all_curricula()[0] == seed

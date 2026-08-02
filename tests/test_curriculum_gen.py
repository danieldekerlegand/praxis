"""Subject in, curriculum out — with the model mocked.

No test touches the network: `praxis.llm._urlopen` is the one seam (see test_llm.py),
and the generator takes an injectable client so the parsing and validation branches can
be driven directly.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import CurriculumError, load_subject  # noqa: E402
from praxis import llm  # noqa: E402
from praxis.curriculum_gen import (  # noqa: E402
    MAX_MODULES,
    SYSTEM_PROMPT,
    extract_json,
    generate_and_save,
    generate_curriculum,
)

CURRICULUM = {
    "title": "Conversational Portuguese",
    "blurb": "Hold a real conversation in Brazilian Portuguese.",
    "modules": [
        {
            "title": "Sounds and Survival Phrases",
            "blurb": "Pronunciation first, so nothing learned later has to be unlearned.",
            "topics": [
                {"title": "The Vowel System", "slug": "vowel-system", "runnable": False},
                {"title": "Greetings and Introductions", "runnable": False},
            ],
        },
        {
            "title": "Drilling with Python",
            "topics": [{"title": "Spaced Repetition from Scratch", "runnable": True}],
        },
    ],
}

GOAL = "I want to hold a conversation in Brazilian Portuguese"


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path):
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "subjects"))
    return tmp_path / "subjects"


class FakeClient:
    """An LLMClient stand-in: records the call, replies with whatever it was given."""

    def __init__(self, reply: str, model: str = "test-model"):
        self.reply, self.calls = reply, []
        self.config = llm.LLMConfig(provider="openai", model=model, api_key="k")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        return self.reply


def test_the_goal_and_the_schema_reach_the_model():
    client = FakeClient(json.dumps(CURRICULUM))
    generate_curriculum(GOAL, client=client, modules=4, topics_per_module=5)

    (call,) = client.calls
    assert call["system"] == SYSTEM_PROMPT
    assert GOAL in call["prompt"]
    assert '"modules"' in call["prompt"]  # the schema it must answer in
    assert "About 4 modules" in call["prompt"]
    assert "About 5 topics per module" in call["prompt"]


def test_a_generated_curriculum_is_a_subject_ready_to_scaffold():
    client = FakeClient(json.dumps(CURRICULUM), model="claude-opus-5")
    subject = generate_curriculum(GOAL, client=client)

    assert subject.slug == "conversational-portuguese"
    assert subject.goal == GOAL
    assert subject.model == "claude-opus-5"  # provenance, not a guess
    assert subject.n_topics == 3
    assert [m.dir for m in subject.modules] == [
        "subjects/conversational-portuguese/01-sounds-and-survival-phrases",
        "subjects/conversational-portuguese/02-drilling-with-python",
    ]
    assert subject.modules[0].topics[0].runnable is False
    assert subject.modules[1].topics[0].runnable is True


def test_generate_and_save_persists_for_review(subjects_root):
    subject = generate_and_save(GOAL, client=FakeClient(json.dumps(CURRICULUM)))

    path = subjects_root / "conversational-portuguese" / "curriculum.json"
    assert path.is_file()
    assert load_subject("conversational-portuguese") == subject
    # Nothing is scaffolded yet: defining a subject writes exactly one file.
    assert list(subjects_root.rglob("*.ipynb")) == []


def test_an_empty_goal_never_reaches_the_model():
    client = FakeClient(json.dumps(CURRICULUM))
    with pytest.raises(CurriculumError, match="needs a goal"):
        generate_curriculum("   ", client=client)
    assert client.calls == []


def test_module_and_topic_counts_are_clamped():
    client = FakeClient(json.dumps(CURRICULUM))
    generate_curriculum(GOAL, client=client, modules=500, topics_per_module="junk")
    assert f"About {MAX_MODULES} modules" in client.calls[0]["prompt"]
    assert "About 6 topics per module" in client.calls[0]["prompt"]  # the default


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps(CURRICULUM),
        f"```json\n{json.dumps(CURRICULUM)}\n```",
        f"Here you go:\n\n```\n{json.dumps(CURRICULUM)}\n```\n",
    ],
)
def test_json_survives_however_the_model_wraps_it(reply):
    assert extract_json(reply)["title"] == "Conversational Portuguese"


@pytest.mark.parametrize(
    "reply, message",
    [
        ("I'd rather not.", "no JSON object"),
        ("{ nope: }", "not valid JSON"),
        ("[1, 2, 3]", "no JSON object"),
    ],
)
def test_a_reply_that_is_not_a_curriculum_is_an_error(reply, message):
    with pytest.raises(CurriculumError, match=message):
        extract_json(reply)


def test_a_well_formed_reply_with_no_modules_is_still_rejected():
    client = FakeClient(json.dumps({"title": "Empty", "modules": []}))
    with pytest.raises(CurriculumError, match="no modules"):
        generate_curriculum(GOAL, client=client)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_end_to_end_over_a_mocked_provider(monkeypatch, subjects_root):
    """The real LLMClient, the real wire format, a canned reply — and no network."""
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data)
        return _Response(
            json.dumps(
                {"choices": [{"message": {"content": f"```json\n{json.dumps(CURRICULUM)}\n```"}}]}
            ).encode()
        )

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    config = llm.LLMConfig(provider="openai", model="gpt-4o", api_key="test-key")
    subject = generate_and_save(GOAL, client=llm.LLMClient(config))

    assert sent["url"] == "https://api.openai.com/v1/chat/completions"
    assert sent["body"]["messages"][0]["role"] == "system"
    assert GOAL in sent["body"]["messages"][1]["content"]
    assert subject.title == "Conversational Portuguese"
    assert (subjects_root / "conversational-portuguese" / "curriculum.json").is_file()

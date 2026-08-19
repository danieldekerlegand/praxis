"""A posting in, a structured requirement list out — with the model mocked.

This is the JD funnel's one model-backed band, so the suite's job is the same as
`tests/test_curriculum_gen.py`'s: no test touches the network, the extractor takes an
injectable client, and every parsing and validation branch is driven directly.

The posting is the real fixture `tests/test_jd.py` imports, not a string this suite made
up, because the band's strongest claim is about `evidence`: a requirement's quote has to
appear in the posting. Testing that against invented text would test nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import jd, jd_extract, llm  # noqa: E402
from praxis.jd_extract import (  # noqa: E402
    KINDS,
    SYSTEM_PROMPT,
    JDExtractError,
    build_requirements,
    extract_requirements,
    requirements_failures,
    requirements_from_reply,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jd"

# Every `evidence` below is a line of that file, which is what makes the validator's
# anti-fabrication rule testable rather than decorative.
REQUIREMENTS = [
    {
        "name": "Kubernetes",
        "kind": "tool",
        "importance": "required",
        "evidence": "Deep Kubernetes experience: you have debugged a CNI, not just applied YAML.",
        "note": "",
    },
    {
        "name": "Terraform",
        "kind": "technology",  # an alias, normalized to "tool"
        "evidence": "Infrastructure as code as a default, Terraform preferred.",
    },
    {
        "name": "Go",
        "kind": "tool",
        "importance": "must-have",  # an alias, normalized to "required"
        "evidence": "Strong Go or Python, and the judgement to know which one a problem wants.",
    },
    {
        "name": "Incident response",
        "kind": "competency",
        "importance": "required",
        "evidence": "Carry the pager one week in six, and lead blameless incident reviews.",
        "note": "one week in six",
    },
    {
        "name": "eBPF",
        "kind": "tool",
        "importance": "nice-to-have",  # an alias, normalized to "preferred"
        "evidence": "Experience with eBPF based tooling.",
    },
]


@pytest.fixture
def posting() -> dict:
    """The canonical document band 74 would have written, from the real fixture file."""
    name, data = "senior-platform-engineer.txt", (FIXTURES / "senior-platform-engineer.txt").read_bytes()
    return jd.document_from_upload(name, data)


class FakeClient:
    """An LLMClient stand-in: records each call, replies with the next scripted reply."""

    def __init__(self, *replies: str, model: str = "test-model"):
        self.replies, self.calls = list(replies), []
        self.config = llm.LLMConfig(provider="openai", model=model, api_key="k")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


def reply(requirements=None, *, fenced: bool = False) -> str:
    body = json.dumps({"requirements": REQUIREMENTS if requirements is None else requirements})
    return f"Here you go:\n\n```json\n{body}\n```\n" if fenced else body


# --- the ask ----------------------------------------------------------------


def test_the_posting_and_the_schema_reach_the_model(posting):
    client = FakeClient(reply())
    extract_requirements(posting, client=client, limit=12)

    (call,) = client.calls
    assert call["system"] == SYSTEM_PROMPT
    assert "Deep Kubernetes experience" in call["prompt"]  # the posting itself
    assert '"requirements"' in call["prompt"]              # the schema it must answer in
    assert "At most 12 requirements" in call["prompt"]
    assert "VERBATIM" in call["prompt"]                    # the rule the validator enforces


def test_a_posting_with_no_text_is_refused_before_the_model_is_called():
    client = FakeClient(reply())
    with pytest.raises(JDExtractError, match="no text"):
        extract_requirements({"id": "x", "title": "x", "text": "   "}, client=client)
    assert client.calls == []


# --- the forgiving parse ----------------------------------------------------


@pytest.mark.parametrize("fenced", [False, True], ids=["bare", "fenced"])
def test_extraction_normalizes_either_json_variant(posting, fenced):
    payload = extract_requirements(posting, client=FakeClient(reply(fenced=fenced)))

    assert payload["version"] == jd_extract.REQUIREMENTS_VERSION
    assert payload["jd"] == posting["id"]
    assert payload["extracted_by"] == "test-model"
    assert payload["count"] == len(payload["requirements"]) == len(REQUIREMENTS)

    by_name = {r["name"]: r for r in payload["requirements"]}
    assert set(by_name) == {"Kubernetes", "Terraform", "Go", "Incident response", "eBPF"}
    assert {r["kind"] for r in payload["requirements"]} <= set(KINDS)
    assert by_name["Terraform"]["kind"] == "tool"           # "technology" aliased
    assert by_name["Go"]["importance"] == "required"        # "must-have" aliased
    assert by_name["eBPF"]["importance"] == "preferred"     # "nice-to-have" aliased
    assert by_name["Terraform"]["importance"] == "required"  # omitted reads as required
    assert by_name["Incident response"]["id"] == "incident-response"
    assert by_name["Kubernetes"]["note"] == ""              # omitted, not missing
    for requirement in payload["requirements"]:
        assert requirement["evidence"] in posting["text"].replace("\n", " ")


def test_prose_with_no_json_in_it_is_a_failure_not_an_empty_list(posting):
    with pytest.raises(Exception) as exc:
        extract_requirements(posting, client=FakeClient("I could not read that posting."))
    assert "JSON" in str(exc.value)


def test_a_reply_with_no_requirements_is_refused(posting):
    with pytest.raises(JDExtractError, match="no requirements"):
        extract_requirements(posting, client=FakeClient(json.dumps({"requirements": []})))


# --- normalizing ------------------------------------------------------------


def test_the_same_requirement_twice_is_one_requirement():
    twice = REQUIREMENTS + [dict(REQUIREMENTS[0], name="kubernetes")]
    requirements = requirements_from_reply({"requirements": twice})
    assert [r["name"] for r in requirements].count("Kubernetes") == 1
    assert len(requirements) == len(REQUIREMENTS)


def test_a_nameless_entry_is_dropped_rather_than_kept_as_a_blank():
    requirements = requirements_from_reply(
        {"requirements": [{"kind": "tool", "evidence": "x"}, REQUIREMENTS[0]]}
    )
    assert [r["name"] for r in requirements] == ["Kubernetes"]


def test_a_well_formed_list_validates_against_the_posting(posting):
    payload = build_requirements(posting, requirements_from_reply({"requirements": REQUIREMENTS}))
    assert requirements_failures(payload, posting=posting["text"]) == []


# --- model-backed only ------------------------------------------------------


def test_there_is_no_local_extractor_without_a_key(monkeypatch, tmp_path, posting):
    """No key configured means no requirements — nothing here invents one locally."""
    for name in ("PRAXIS_LLM_API_KEY", "PRAXIS_LLM_PROVIDER", "PRAXIS_LLM_BASE_URL",
                 "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AGORA_BASE_URL", "PRAXIS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm, "default_config_path", lambda: tmp_path / "missing.json")

    with pytest.raises(llm.LLMConfigError):
        extract_requirements(posting)


# --- the strict half: what a payload is rejected for ------------------------


def broken(**changes) -> list[dict]:
    """The good list with its first requirement damaged the way a model damages one."""
    first = dict(REQUIREMENTS[0])
    for key, value in changes.items():
        if value is None:
            first.pop(key, None)
        else:
            first[key] = value
    return [first] + REQUIREMENTS[1:]


@pytest.mark.parametrize(
    "damage, expected",
    [
        ({"kind": "vibes"}, "'kind' is 'vibes'"),
        ({"kind": None}, "'kind' is nothing"),
        ({"kind": 7}, "'kind' is nothing"),
        ({"evidence": None}, "'evidence' has to quote the line"),
        ({"evidence": "yes"}, "'evidence' has to quote the line"),
        ({"name": 42}, "no usable 'name'"),
        ({"importance": "someday"}, "'importance' is 'someday'"),
        (
            {"evidence": "You will be issued a company helicopter on your first day."},
            "does not appear in the posting",
        ),
    ],
    ids="bad-kind no-kind kind-not-a-string no-evidence short-evidence "
        "name-not-a-string bad-importance invented-evidence".split(),
)
def test_an_unusable_requirement_is_rejected_with_a_sentence_naming_it(
    posting, damage, expected
):
    payload = build_requirements(posting, requirements_from_reply({"requirements": broken(**damage)}))
    failures = requirements_failures(payload, posting=posting["text"])

    assert any(expected in f for f in failures), failures
    # The complaint is a sentence a reader could act on, not a code or a boolean.
    assert all(len(f) > 40 and f == f.strip() for f in failures), failures


def test_a_name_the_model_sent_but_broke_is_rejected_rather_than_dropped(posting):
    """A missing name key is filler; an unreadable one is a mistake worth naming back."""
    requirements = requirements_from_reply({"requirements": broken(name=42)})

    assert len(requirements) == len(REQUIREMENTS)  # not silently one shorter
    assert requirements_failures(
        build_requirements(posting, requirements), posting=posting["text"]
    )


def test_a_payload_that_is_not_a_document_is_refused():
    assert requirements_failures(["Kubernetes"]) == [
        "the requirements payload does not hold a JSON object"
    ]
    assert requirements_failures({"version": 99, "requirements": REQUIREMENTS}) == [
        "unsupported requirements version 99"
    ]


# --- repair -----------------------------------------------------------------


def test_a_rejected_payload_is_repaired_with_the_validators_own_sentences(posting):
    """Attempt two carries the complaint and the draft — the model is not asked to guess."""
    client = FakeClient(reply(broken(kind="vibes")), reply())
    payload = extract_requirements(posting, client=client)

    assert len(client.calls) == 2
    assert payload["count"] == len(REQUIREMENTS)
    assert {r["kind"] for r in payload["requirements"]} <= set(KINDS)

    first, second = (call["prompt"] for call in client.calls)
    assert "FAILED validation" not in first
    assert "FAILED validation" in second
    assert "'kind' is 'vibes'" in second          # the validator's own sentence
    assert '"Terraform"' in second                # its own draft, quoted back
    assert first.split("Your previous answer")[0] in second  # the whole original ask


def test_a_repair_that_still_fails_is_a_failure_not_a_partial_list(posting):
    """The four good requirements are not returned without the one that failed."""
    client = FakeClient(reply(broken(evidence="We are a rocketship with great snacks.")))

    with pytest.raises(JDExtractError) as exc:
        extract_requirements(posting, client=client)

    assert len(client.calls) == 2                      # asked, repaired, gave up
    assert exc.value.attempts == 2
    assert "did not validate" in str(exc.value)
    assert any("does not appear in the posting" in f for f in exc.value.failures)
    assert "Terraform" not in str(exc.value)           # no partial list smuggled out


def test_one_attempt_means_no_repair(posting):
    client = FakeClient(reply(broken(kind="vibes")), reply())

    with pytest.raises(JDExtractError):
        extract_requirements(posting, client=client, attempts=1)
    assert len(client.calls) == 1


def test_a_reply_with_no_json_in_it_is_repaired_without_a_draft(posting):
    """Nothing parsed means nothing to quote back — the complaint still goes out."""
    client = FakeClient("I could not read that posting.", reply())
    payload = extract_requirements(posting, client=client)

    assert payload["count"] == len(REQUIREMENTS)
    second = client.calls[1]["prompt"]
    assert "no JSON object in the model's reply" in second
    assert "<draft>" not in second

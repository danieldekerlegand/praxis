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

"""The construction agent: a scaffold in, a notebook that passes the gate out.

No test touches the network — `praxis.llm._urlopen` is the one seam (test_llm.py) and
`construct_topic` takes an injectable client, so every branch is driven directly.

The point of most of these is the anti-fabrication contract: content that would not
pass tests/test_notebooks.py must never reach the disk, and must never be flagged ✅.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import (  # noqa: E402
    CurriculumError,
    save_subject,
    subject_from_dict,
    topic_path,
)
from nbstatus import BADGE, notebook_status  # noqa: E402
from praxis import construct, llm  # noqa: E402
from praxis.construct import (  # noqa: E402
    SYSTEM_PROMPT,
    ConstructionError,
    build_notebook,
    cells_from_reply,
    construct_path,
    construct_topic,
    execute_notebook,
    topic_for_path,
    topic_for_rel,
)
from praxis.rubric import gate_failures, notebook_text  # noqa: E402
from scaffold_notebooks import scaffold_subject  # noqa: E402

CURRICULUM = {
    "title": "Embedded Rust",
    "blurb": "Drive real hardware from Rust.",
    "modules": [
        {
            "title": "Foundations",
            "blurb": "The language guarantees that matter on a microcontroller.",
            "topics": [
                {"title": "Ownership and Borrowing", "slug": "ownership", "runnable": True},
                {"title": "Wiring a Dev Board", "slug": "wiring", "runnable": False,
                 "note": "needs hardware"},
            ],
        }
    ],
}

PROSE = (
    "This section is written out in full, the way a refresher for a colleague who "
    "already knows the neighbouring ideas actually reads: concrete, specific, and "
    "unwilling to hand-wave at the part that is genuinely hard. "
)

RESOURCES = (
    "## 8. Resources\n\n"
    "- [The official documentation](https://doc.rust-lang.org/book/)\n"
    "- [The embedded book](https://docs.rust-embedded.org/book/)\n"
    "- [The discovery book](https://docs.rust-embedded.org/discovery/)\n" + PROSE * 3
)


def _section(heading: str, weight: int = 8) -> dict:
    return {"type": "markdown", "source": f"## {heading}\n\n{PROSE * weight}"}


def good_cells(runnable: bool = True) -> list[dict]:
    """A reply that clears every bar: 8 sections, real links, code that compiles."""
    cells = [
        _section("1. What & Why"),
        _section("2. Mental Model"),
        _section("3. Key Concepts"),
        _section("4. Setup"),
    ]
    if runnable:
        cells += [
            {"type": "code", "source": "import math\nprint(round(math.pi, 4))"},
            _section("5. Worked Examples"),
            {"type": "markdown", "source": "### Example 1: the smallest thing that works"},
            {"type": "code", "source": "values = [1, 2, 3]\nprint(sum(values))"},
            {"type": "markdown", "source": "### Example 2: the one that shows the edge"},
            {"type": "code", "source": "import os\nif os.getenv('BOARD_PORT'):\n"
                                       "    print('would flash the board')"},
        ]
    else:
        cells += [
            _section("4b. Not runnable"),
            _section("5. Worked Examples"),
            {"type": "markdown",
             "source": "### Example 1: from the shell\n\nThis topic cannot be driven from "
                       "a Python kernel, so here is the real command:\n\n"
                       "```bash\nprobe-rs list\n```\n" + PROSE * 4},
            {"type": "markdown",
             "source": "### Example 2: the config\n\n```toml\n[build]\ntarget = "
                       "\"thumbv7em-none-eabihf\"\n```\n" + PROSE * 4},
        ]
    cells += [
        _section("6. Gotchas & Pitfalls"),
        _section("7. When to Use vs Alternatives"),
        {"type": "markdown", "source": RESOURCES},
    ]
    return cells


def reply(cells: list[dict]) -> str:
    return json.dumps({"cells": cells})


class FakeClient:
    """An LLMClient stand-in: records each call, replies from a queue."""

    def __init__(self, *replies: str, model: str = "test-model"):
        self.replies, self.calls = list(replies), []
        self.config = llm.LLMConfig(provider="openai", model=model, api_key="k")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    """Constructed notebooks land in a temp dir — never the developer's notebooks/."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def subject():
    subj = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    save_subject(subj)
    scaffold_subject(subj)  # the constructor's real input is a scaffold
    return subj


@pytest.fixture
def runnable(subject):
    return subject.modules[0], subject.modules[0].topics[0]


@pytest.fixture
def conceptual(subject):
    return subject.modules[0], subject.modules[0].topics[1]


# --- the call ---------------------------------------------------------------


def test_the_topic_the_rubric_and_the_context_reach_the_model(runnable, subject):
    module, topic = runnable
    client = FakeClient(reply(good_cells()))

    construct_topic(module, topic, client=client, subject=subject)

    (call,) = client.calls
    assert call["system"] == SYSTEM_PROMPT
    assert "Ownership and Borrowing" in call["prompt"]
    assert "Foundations" in call["prompt"]                    # its module
    assert "drive a microcontroller from Rust" in call["prompt"]  # the learner's goal
    assert "Wiring a Dev Board" in call["prompt"]             # sibling, to cross-link
    for section in ("What & Why", "Mental Model", "Key Concepts", "Setup",
                    "Worked Examples", "Gotchas", "When to Use", "Resources"):
        assert section in call["prompt"]
    assert "%pip install" in call["prompt"]      # runnable topics get the install rule
    assert "AT LEAST TWO" in call["prompt"]


def test_a_conceptual_topic_is_told_not_to_fake_code(conceptual):
    module, topic = conceptual
    client = FakeClient(reply(good_cells(runnable=False)))

    construct_topic(module, topic, client=client)

    prompt = client.calls[0]["prompt"]
    assert "NO code cells" in prompt
    assert "needs hardware" in prompt  # the topic's note


# --- the notebook it writes -------------------------------------------------


def test_a_constructed_notebook_passes_the_completion_gate(runnable, subject):
    module, topic = runnable
    path = topic_path(module, topic)
    assert notebook_status(path)[0] == "scaffold"  # 🔴 before

    result = construct_topic(module, topic, client=FakeClient(reply(good_cells())),
                             subject=subject)

    assert result.status == "constructed"
    assert result.attempts == 1
    assert result.ok and result.path == path
    # ✅ after — the badge the launcher shows.
    assert notebook_status(path)[0] == "complete"
    assert BADGE[notebook_status(path)[0]] == "✅"
    nb = json.loads(path.read_text())
    nbformat.read(str(path), as_version=4)          # valid nbformat
    assert gate_failures(nb) == []                  # tests/test_notebooks.py's own rules
    assert nb["metadata"]["praxis"]["status"] == "complete"
    assert nb["metadata"]["praxis"]["constructed_by"] == "test-model"
    assert nb["metadata"]["praxis"]["slug"] == "ownership"
    assert len([c for c in nb["cells"] if c["cell_type"] == "code"]) >= 2
    assert nb["cells"][0]["source"] == ["# Ownership and Borrowing\n\n"
                                        "**Foundations**  ·  runnable"]
    assert "scaffold" not in notebook_text(nb).lower()


def test_a_conceptual_notebook_is_complete_without_code_cells(conceptual):
    module, topic = conceptual
    result = construct_topic(module, topic,
                             client=FakeClient(reply(good_cells(runnable=False))))

    assert result.status == "constructed"
    nb = json.loads(result.path.read_text())
    assert [c for c in nb["cells"] if c["cell_type"] == "code"] == []
    assert gate_failures(nb) == []
    assert notebook_status(result.path)[0] == "complete"
    assert "not Python-runnable" in nb["cells"][0]["source"][0]


# --- anti-fabrication -------------------------------------------------------


@pytest.mark.parametrize(
    "cells, expected",
    [
        # Thin: real sections, no substance.
        ([{"type": "markdown", "source": f"## {h}\n\nx"} for h in (
            "1. What & Why", "2. Mental Model", "3. Key Concepts", "4. Setup",
            "5. Worked Examples", "6. Gotchas", "7. When to Use", "8. Resources")],
         "too thin"),
        # Placeholder text survived.
        (good_cells()[:-1] + [{"type": "markdown", "source": "## 8. Resources\n\nTODO"}],
         "placeholder text remains"),
        # A section was dropped.
        (good_cells()[1:], "missing rubric sections"),
        # Links that don't exist.
        (good_cells()[:-1] + [{"type": "markdown", "source":
            "## 8. Resources\n\n- https://example.com/docs\n- https://example.com/api\n"
            "- https://example.com/guide\n" + PROSE * 4}],
         "placeholder URLs"),
        # Not enough links.
        (good_cells()[:-1] + [{"type": "markdown", "source":
            "## 8. Resources\n\n- [the docs](https://doc.rust-lang.org/book/)\n" + PROSE * 4}],
         "real https:// links"),
        # Code that could not possibly have run.
        (good_cells()[:-4] + [{"type": "code", "source": "def broken(:\n    pass"}]
         + good_cells()[-3:],
         "not valid Python"),
    ],
)
def test_content_that_fails_the_rubric_is_never_written(runnable, cells, expected):
    module, topic = runnable
    path = topic_path(module, topic)
    before = path.read_text()

    result = construct_topic(module, topic, client=FakeClient(reply(cells)), attempts=1)

    assert result.status == "failed"
    assert not result.ok
    assert any(expected in f for f in result.failures), result.failures
    # The scaffold is untouched, and still 🔴 — nothing was flagged complete.
    assert path.read_text() == before
    assert notebook_status(path)[0] == "scaffold"


def test_a_reply_that_is_not_a_notebook_fails_without_writing(runnable):
    module, topic = runnable
    before = topic_path(module, topic).read_text()

    result = construct_topic(module, topic, client=FakeClient("I'd rather not."),
                             attempts=1)

    assert result.status == "failed"
    assert "no JSON object" in result.detail
    assert topic_path(module, topic).read_text() == before


def test_an_llm_error_is_reported_not_raised(runnable):
    module, topic = runnable

    class Boom(FakeClient):
        def complete(self, prompt, **kwargs):
            raise llm.LLMError("provider exploded")

    result = construct_topic(module, topic, client=Boom(), attempts=2)

    assert result.status == "failed"
    assert "provider exploded" in result.detail


@pytest.mark.parametrize("data", [{}, {"cells": []}, {"cells": [{"source": "  "}]}])
def test_an_empty_cell_list_is_an_error(data):
    with pytest.raises(ConstructionError):
        cells_from_reply(data)


def test_write_false_grades_without_touching_the_disk(runnable):
    module, topic = runnable
    before = topic_path(module, topic).read_text()

    result = construct_topic(module, topic, client=FakeClient(reply(good_cells())),
                             write=False)

    assert result.status == "constructed"
    assert topic_path(module, topic).read_text() == before


# --- the repair loop --------------------------------------------------------


def test_a_failing_draft_is_sent_back_with_the_gate_s_complaints(runnable):
    module, topic = runnable
    thin = [{"type": "markdown", "source": "## 1. What & Why\n\nx"}]
    client = FakeClient(reply(thin), reply(good_cells()))

    result = construct_topic(module, topic, client=client, attempts=3)

    assert result.status == "constructed"
    assert result.attempts == 2
    assert len(client.calls) == 2
    repair = client.calls[1]["prompt"]
    assert "FAILED the automated completion gate" in repair
    assert "missing rubric sections" in repair
    assert "<draft>" in repair          # its own draft came back with the complaints
    assert notebook_status(result.path)[0] == "complete"


def test_attempts_are_bounded(runnable):
    module, topic = runnable
    client = FakeClient(reply([{"type": "markdown", "source": "## 1. What & Why\n\nx"}]))

    result = construct_topic(module, topic, client=client, attempts=2)

    assert result.status == "failed"
    assert result.attempts == 2 and len(client.calls) == 2


# --- idempotence ------------------------------------------------------------


def test_an_already_complete_notebook_is_skipped_not_rewritten(runnable):
    module, topic = runnable
    client = FakeClient(reply(good_cells()))
    first = construct_topic(module, topic, client=client)
    written = first.path.read_text()

    again = construct_topic(module, topic, client=client)

    assert again.status == "skipped"
    assert again.ok and again.detail == "already complete"
    assert len(client.calls) == 1          # no second call, no tokens spent
    assert first.path.read_text() == written


def test_force_rebuilds_an_already_complete_notebook(runnable):
    module, topic = runnable
    construct_topic(module, topic, client=FakeClient(reply(good_cells())))

    rebuilt = construct_topic(
        module, topic, force=True,
        client=FakeClient(reply(good_cells()[:-1] + [{"type": "markdown", "source":
            RESOURCES + "\n\nRewritten with a second pass."}])),
    )

    assert rebuilt.status == "constructed"
    assert "Rewritten with a second pass." in rebuilt.path.read_text()


def test_a_rebuild_keeps_the_scaffold_s_metadata(runnable, subject):
    """The praxis block is updated, not replaced — provenance survives a rebuild."""
    module, topic = runnable
    scaffold = json.loads(topic_path(module, topic).read_text())
    nb = build_notebook(module, topic, cells_from_reply(json.loads(reply(good_cells()))),
                        model="m", scaffold=scaffold)

    assert nb["metadata"]["praxis"]["recommended"] is False
    assert nb["metadata"]["praxis"]["domain"] == module.dir
    assert nb["metadata"]["kernelspec"]["name"] == "python3"
    assert nb["metadata"]["praxis"]["constructed"]


# --- constructing many ------------------------------------------------------


class TopicClient:
    """Answers each prompt with cells of the right shape for the topic it describes."""

    def __init__(self, bad: tuple[str, ...] = (), model: str = "test-model"):
        self.bad, self.calls = bad, []
        self.config = llm.LLMConfig(provider="openai", model=model, api_key="k")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append(prompt)
        # Match the <topic> block, not the whole prompt: every prompt lists its siblings.
        if any(f"<topic>\n{title}\n</topic>" in prompt for title in self.bad):
            return reply([{"type": "markdown", "source": "## 1. What & Why\n\nthin."}])
        return reply(good_cells(runnable="NO code cells" not in prompt))


def test_a_batch_constructs_every_topic_of_a_curriculum(subject):
    client = TopicClient()

    results = construct.construct_subject(subject, client=client)

    assert [r.status for r in results] == ["constructed", "constructed"]
    assert len(client.calls) == 2
    for module in subject.modules:
        for topic in module.topics:
            path = topic_path(module, topic)
            assert notebook_status(path)[0] == "complete"
            assert gate_failures(json.loads(path.read_text())) == []


def test_rerunning_a_batch_skips_what_is_already_complete(subject):
    construct.construct_subject(subject, client=TopicClient())
    before = {p: p.read_bytes() for p in subject.dir.rglob("*.ipynb")}

    client = TopicClient()
    results = construct.construct_subject(subject, client=client)

    assert [r.status for r in results] == ["skipped", "skipped"]
    assert client.calls == []                                   # nothing was spent
    assert {p: p.read_bytes() for p in before} == before         # nothing was rewritten


def test_a_resumed_batch_finishes_only_what_is_missing(subject):
    module = subject.modules[0]
    construct.construct_topic(module, module.topics[0], client=TopicClient())

    results = construct.construct_subject(subject, client=TopicClient())

    assert [(r.slug, r.status) for r in results] == [
        ("ownership", "skipped"), ("wiring", "constructed"),
    ]


def test_a_topic_the_model_keeps_failing_does_not_strand_the_rest(subject):
    module = subject.modules[0]
    scaffold = topic_path(module, module.topics[0]).read_bytes()

    results = construct.construct_subject(
        subject, client=TopicClient(bad=("Ownership and Borrowing",)), attempts=2)

    assert [r.status for r in results] == ["failed", "constructed"]
    assert results[0].failures                                   # the grader's sentences
    assert topic_path(module, module.topics[0]).read_bytes() == scaffold  # still 🔴
    assert notebook_status(topic_path(module, module.topics[1]))[0] == "complete"


def test_a_batch_reports_each_topic_as_it_starts_and_finishes(subject):
    seen = []

    construct.construct_subject(
        subject, client=TopicClient(),
        on_start=lambda d, t: seen.append(("start", d.dir, t.slug)),
        on_result=lambda r, d: seen.append((r.status, d.dir, r.slug)),
    )

    module = subject.modules[0].dir
    assert seen == [
        ("start", module, "ownership"), ("constructed", module, "ownership"),
        ("start", module, "wiring"), ("constructed", module, "wiring"),
    ]


def test_a_finished_curriculum_needs_no_provider_key(subject, monkeypatch):
    """Re-running to confirm a subject is done must not demand a configured model."""
    construct.construct_subject(subject, client=TopicClient())

    def no_key():
        raise llm.LLMConfigError("no API key for provider 'anthropic'")

    monkeypatch.setattr(construct, "LLMClient", no_key)
    results = construct.construct_subject(subject)

    assert [r.status for r in results] == ["skipped", "skipped"]


def test_a_domain_can_be_given_the_topics_to_build(subject):
    """A filesystem domain enumerates none of its own — the caller passes them."""
    module = subject.modules[0]

    results = construct.construct_domain(
        module, subject=subject, topics=[module.topics[1]], client=TopicClient())

    assert [(r.slug, r.status) for r in results] == [("wiring", "constructed")]
    assert notebook_status(topic_path(module, module.topics[0]))[0] == "scaffold"


# --- resolving a path back to its curriculum entry --------------------------


def test_a_path_resolves_to_its_subject_topic(runnable, subject):
    module, topic = runnable

    found_module, found_topic, found_subject = topic_for_path(topic_path(module, topic))

    assert found_topic == topic
    assert found_module.dir == module.dir
    assert found_subject.slug == subject.slug


def test_construct_path_fills_the_notebook_at_that_path(runnable, monkeypatch):
    module, topic = runnable
    monkeypatch.setattr(construct, "LLMClient", lambda: FakeClient(reply(good_cells())))

    result = construct_path(topic_path(module, topic))

    assert result.status == "constructed"
    assert notebook_status(result.path)[0] == "complete"


def test_a_path_with_no_notebook_is_an_error(tmp_path):
    with pytest.raises(CurriculumError, match="no notebook"):
        topic_for_path(tmp_path / "nope.ipynb")


def test_a_library_rel_resolves_to_its_subject_topic(runnable, subject):
    """The UI holds `rel`, not a path — and a relocated subject dir must not break it."""
    module, topic = runnable

    found_module, found_topic, found_subject = topic_for_rel(
        f"{module.dir}/{topic.slug}.ipynb")

    assert found_topic == topic
    assert found_module.dir == module.dir
    assert found_subject.slug == subject.slug


def test_a_seed_rel_resolves_to_its_seed_domain():
    domain, topic, subject = topic_for_rel("01-symbolic-ai-logic/swi-prolog.ipynb")

    assert (domain.dir, topic.slug, subject) == ("01-symbolic-ai-logic", "swi-prolog", None)


def test_a_nested_legacy_rel_resolves_to_the_directory_it_sits_in():
    """topic_path() has to land back on the same file, or construction writes elsewhere."""
    rel = "11-devops-mlops-infra/job-orchestration-tools/argo-workflows.ipynb"

    domain, topic, _ = topic_for_rel(rel)

    assert topic_path(domain, topic) == ROOT / "notebooks" / rel


@pytest.mark.parametrize("rel", ["", "../pyproject.toml", "a/../../etc/passwd"])
def test_a_rel_that_escapes_the_library_is_refused(rel):
    with pytest.raises(CurriculumError):
        topic_for_rel(rel)


# --- execution ---------------------------------------------------------------


def test_a_missing_jupyter_is_a_skip_not_a_failure(runnable, monkeypatch):
    module, topic = runnable

    def no_jupyter(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(construct.subprocess, "run", no_jupyter)
    ok, message = execute_notebook(topic_path(module, topic))

    assert ok and "skipped" in message


def test_a_notebook_that_errors_under_jupyter_is_a_failure(runnable, monkeypatch):
    module, topic = runnable

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "CellExecutionError: name 'nope' is not defined"

    monkeypatch.setattr(construct.subprocess, "run", lambda *a, **k: Proc())
    ok, message = execute_notebook(topic_path(module, topic))

    assert not ok and "CellExecutionError" in message


# --- end to end over a mocked provider --------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_end_to_end_over_a_mocked_provider(monkeypatch, runnable, subject):
    """The real LLMClient, the real wire format, a canned reply — and no network."""
    module, topic = runnable
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data)
        return _Response(json.dumps(
            {"choices": [{"message": {"content": f"```json\n{reply(good_cells())}\n```"}}]}
        ).encode())

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    config = llm.LLMConfig(provider="openai", model="gpt-4o", api_key="test-key")

    result = construct_topic(module, topic, client=llm.LLMClient(config), subject=subject)

    assert sent["url"] == "https://api.openai.com/v1/chat/completions"
    assert "Ownership and Borrowing" in sent["body"]["messages"][1]["content"]
    assert result.status == "constructed"
    assert notebook_status(result.path)[0] == "complete"
    assert gate_failures(json.loads(result.path.read_text())) == []


# --- the CLI ----------------------------------------------------------------


def test_cli_constructs_a_notebook_by_path(runnable, monkeypatch, capsys):
    module, topic = runnable
    monkeypatch.setattr(construct, "LLMClient", lambda: FakeClient(reply(good_cells())))

    assert construct._main([str(topic_path(module, topic))]) == 0
    assert "✅" in capsys.readouterr().out
    assert notebook_status(topic_path(module, topic))[0] == "complete"


def test_cli_reports_a_failure(runnable, monkeypatch, capsys):
    module, topic = runnable
    monkeypatch.setattr(
        construct, "LLMClient",
        lambda: FakeClient(reply([{"type": "markdown", "source": "## 1. What & Why\n\nx"}])),
    )

    assert construct._main(["--force", str(topic_path(module, topic))]) == 1
    assert "⚠️" in capsys.readouterr().out


def test_cli_without_a_path_is_usage(capsys):
    assert construct._main([]) == 2
    assert "python -m praxis.construct" in capsys.readouterr().err

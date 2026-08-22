"""Driving a praxis tasklist through Chief's headless entry point.

What is under test is the **wiring**, not a run: no model is called, no network is
touched, and the driver is a scripted fake `chief` on disk that prints the contract's
lines and exits with a code. The two properties that matter are asserted against it —

- the run is started through the headless entry point (`--headless`) and routed through
  the local-inference preset (`--preset=local` plus its two variables), with no
  `--provider`/`--model` pair chief would refuse next to it; and
- the outcome is read from the **machine-readable** records (`chief: run-id=`,
  `chief: summary=`, the exit code) and never scraped out of the human summary block —
  the fake prints a human block that says the opposite of its summary, and the parsed
  result follows the summary.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import headless  # noqa: E402
from praxis import tasklist as tasklists  # noqa: E402
from praxis.headless import (  # noqa: E402
    EXIT_OUTCOMES,
    HeadlessError,
    LocalPreset,
    command,
    ensure_tasklist,
    parse_run,
    records,
    run_tasklists,
    run_units,
    unfinished,
)
from praxis.tasklist import TasklistError, Unit  # noqa: E402

ENDPOINT = "http://127.0.0.1:11434/v1"
MODEL = "ollama/qwen2.5-coder:14b"

UNIT = Unit(
    name="gate-01-symbolic-ai-logic",
    kind="backfill",
    slug="01-symbolic-ai-logic",
    title="Symbolic AI & Logic",
    command="python3 -m praxis.backfill 01-symbolic-ai-logic",
    pending=("01-symbolic-ai-logic/datalog.ipynb",),
    done=3,
    touches=("notebooks/01-symbolic-ai-logic",),
    category="fix",
)

# A human summary block that says the RUN WENT FINE, printed next to machine-readable
# records that say it did not. Anything that reads this rather than the records reports
# a merge that never happened.
HUMAN_BLOCK = """\
  schedule: 2 tasklists, -p 2
  == summary ==
  All tasklists merged successfully.
  auth      MERGED
  billing   MERGED
  nothing left to do — 2/2 complete
"""


def contract_lines(
    *, run_id="praxis-abc-123-456", outcome="merged", exit_code=0, tasklists_rows=(),
    include_exit=True,
):
    """The lines a headless chief run prints, in the order it prints them."""
    summary = {
        "runId": run_id, "repo": "/tmp/praxis", "base": "main",
        "state": "/tmp/praxis/.chief/state", "outcome": outcome, "exit": exit_code,
        "ok": exit_code == 0, "tasklists": list(tasklists_rows),
    }
    lines = [
        f"chief: run-id={run_id}",
        "chief: run-file=/tmp/runs/54321.run",
        f"chief: events=/tmp/runs/{run_id}.events.jsonl",
        "chief: state=/tmp/praxis/.chief/state",
        HUMAN_BLOCK,
        f"chief: outcome={outcome}",
    ]
    if include_exit:
        lines.append(f"chief: exit={exit_code}")
    lines.append("chief: summary=" + json.dumps(summary))
    return "\n".join(lines) + "\n"


def a_unit_with_work() -> Unit:
    """A real unit off the live library — the tests that resolve names need a backlog."""
    unit = next((u for u in tasklists.library_units() if u.pending), None)
    if unit is None:  # pragma: no cover - the seed library ships 221 pending topics
        pytest.skip("the whole seed library is gated; no unit has work")
    return unit


def row(name, outcome, status=""):
    return {"name": name, "outcome": outcome, "state": "done" if outcome == "merged"
            else "failed", "status": status or outcome.upper(), "attempts": 1,
            "log": f"/tmp/praxis/.chief/state/parallel/{name}.log"}


FAKE_CHIEF = """\
#!{python}
# A scripted `chief`: it records how it was invoked, prints a canned stream and exits
# with a canned code. It never runs an agent and never opens a socket.
import json, os, sys

record = os.environ["FAKE_CHIEF_RECORD"]
with open(record, "w") as handle:
    json.dump({{
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "env": {{k: v for k, v in os.environ.items() if k.startswith("CHIEF_")}},
    }}, handle)
sys.stdout.write(os.environ.get("FAKE_CHIEF_STDOUT", ""))
sys.stderr.write(os.environ.get("FAKE_CHIEF_STDERR", ""))
sys.exit(int(os.environ.get("FAKE_CHIEF_EXIT", "0")))
"""


@pytest.fixture
def fake_chief(tmp_path, monkeypatch):
    """A scripted headless driver on disk, and the preset configured to reach it."""
    script = tmp_path / "chief"
    script.write_text(FAKE_CHIEF.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    record = tmp_path / "invocation.json"
    monkeypatch.setenv(headless.CHIEF_BIN_ENV, str(script))
    monkeypatch.setenv("FAKE_CHIEF_RECORD", str(record))
    monkeypatch.setenv("FAKE_CHIEF_STDOUT", contract_lines())
    monkeypatch.setenv("FAKE_CHIEF_STDERR", "")
    monkeypatch.setenv("FAKE_CHIEF_EXIT", "0")
    monkeypatch.setenv(headless.PRESET_ENDPOINT, ENDPOINT)
    monkeypatch.setenv(headless.PRESET_MODEL, MODEL)
    for name in (headless.PRESET_ENDPOINT_ENV, headless.PRESET_API_KEY,
                 headless.PRESET_API_KEY_ENV):
        monkeypatch.delenv(name, raising=False)

    def invocation():
        return json.loads(record.read_text())

    return invocation


# --- the entry point that is used --------------------------------------------


def test_the_run_is_started_through_the_headless_entry_point(fake_chief):
    run = run_tasklists([UNIT.name], parallel=4)

    argv = fake_chief()["argv"]
    assert argv[:2] == ["run", "--headless"]
    assert argv[-1] == UNIT.name
    assert ["-p", "4"] == argv[argv.index("-p"):argv.index("-p") + 2]
    assert run.run_id == "praxis-abc-123-456"


def test_the_run_is_routed_through_the_local_inference_preset(fake_chief):
    run_tasklists([UNIT.name])

    invocation = fake_chief()
    assert f"--preset={headless.PRESET}" in invocation["argv"]
    # The preset IS the provider choice — chief refuses `--local --provider claude`
    # rather than guessing which one is paying, so neither flag may be sent.
    assert "--provider" not in invocation["argv"]
    assert "--model" not in invocation["argv"]
    assert invocation["env"]["CHIEF_PRESET"] == "local"
    assert invocation["env"][headless.PRESET_ENDPOINT] == ENDPOINT
    assert invocation["env"][headless.PRESET_MODEL] == MODEL
    assert invocation["env"]["CHIEF_PROJECT"] == str(tasklists.repo_root())


def test_the_documented_preset_overrides_are_passed_only_when_set(fake_chief, monkeypatch):
    monkeypatch.setenv(headless.PRESET_ENDPOINT_ENV, "LLM_BASE_URL")
    monkeypatch.setenv(headless.PRESET_API_KEY, "local")

    run_tasklists([UNIT.name])

    env = fake_chief()["env"]
    assert env[headless.PRESET_ENDPOINT_ENV] == "LLM_BASE_URL"
    assert env[headless.PRESET_API_KEY] == "local"
    assert headless.PRESET_API_KEY_ENV not in env


def test_an_unconfigured_preset_refuses_before_anything_is_spawned():
    def never(*args, **kwargs):  # pragma: no cover - the point is that it is not called
        raise AssertionError("a run was spawned with the preset unconfigured")

    with pytest.raises(HeadlessError) as excinfo:
        run_tasklists([UNIT.name], preset=LocalPreset(), runner=never)

    message = str(excinfo.value)
    assert headless.PRESET_ENDPOINT in message and headless.PRESET_MODEL in message
    assert "paid provider" in message


def test_a_run_that_cannot_start_leaves_nothing_on_disk(tmp_path):
    """The routing is resolved before the tasklist is generated, not after."""
    with pytest.raises(HeadlessError):
        run_units([UNIT], root=tmp_path, preset=LocalPreset(endpoint="", model=""))

    assert not (tmp_path / "tasks").exists()


def test_the_dry_run_and_no_merge_flags_are_the_ones_chief_documents(fake_chief):
    argv = command([UNIT.name], dry_run=True, no_merge=True, parallel=2, chief="chief")

    assert argv[0] == "chief"
    assert "--dry-run" in argv and "--no-merge" in argv
    assert argv.index("--headless") < argv.index(UNIT.name)


# --- the outcome that is read ------------------------------------------------


def test_the_outcome_comes_from_the_summary_not_the_human_block(fake_chief, monkeypatch):
    monkeypatch.setenv("FAKE_CHIEF_STDOUT", contract_lines(
        outcome="verify-failed", exit_code=4,
        tasklists_rows=[row("auth", "merged", "MERGED @a1b2c3d"),
                        row("billing", "verify-failed", "VERIFY-FAILED")]))
    monkeypatch.setenv("FAKE_CHIEF_EXIT", "4")

    run = run_tasklists(["auth", "billing"])

    # The human block on that same stream said "All tasklists merged successfully."
    assert run.outcome == "verify-failed"
    assert run.exit_code == 4 and not run.ok
    assert [t.outcome for t in run.tasklists] == ["merged", "verify-failed"]
    assert run.named("billing").log.endswith("billing.log")
    assert unfinished(run) == ["billing"]


def test_the_scripted_driver_prints_the_whole_documented_contract():
    """The fixture is only evidence if it emits every line chief's contract names."""
    rec = records(contract_lines())

    assert set(headless.RUN_KEYS) | set(headless.RESULT_KEYS) <= set(rec)


def test_records_keeps_only_the_machine_readable_lines():
    stream = ("noise\n" + HUMAN_BLOCK + "chief: run-id=x\n"
              "  chief: outcome=merged\n" + "chief: not-a-record\n"
              "chief: summary={\"a\": 1}\n")

    assert records(stream) == {"run-id": "x", "outcome": "merged",
                               "summary": '{"a": 1}'}


def test_the_run_id_line_ties_the_stream_to_chiefs_own_records(fake_chief):
    run = run_tasklists([UNIT.name])

    assert run.run_id == "praxis-abc-123-456"
    assert run.events.endswith(".events.jsonl")
    assert run.run_file == "/tmp/runs/54321.run"
    assert run.state == "/tmp/praxis/.chief/state"


@pytest.mark.parametrize("code,outcome", sorted(EXIT_OUTCOMES.items()))
def test_the_exit_code_names_the_outcome_with_no_summary_to_read(code, outcome):
    stream = "" if code in headless.NO_RUN_EXITS else "chief: run-id=r-1\n"

    assert parse_run(stream, code).outcome == outcome


def test_a_stream_with_no_contract_on_it_is_refused_rather_than_scraped():
    with pytest.raises(HeadlessError) as excinfo:
        parse_run(HUMAN_BLOCK, 0)

    assert "run-id" in str(excinfo.value)
    assert "--headless" in str(excinfo.value)


def test_a_declared_exit_that_disagrees_with_the_process_is_refused():
    with pytest.raises(HeadlessError) as excinfo:
        parse_run(contract_lines(outcome="merged", exit_code=0), 6)

    assert "disagrees" in str(excinfo.value)


def test_a_summary_that_is_not_json_is_refused():
    with pytest.raises(HeadlessError) as excinfo:
        parse_run("chief: run-id=r-1\nchief: summary=not json\n", 0)

    assert "not JSON" in str(excinfo.value)


def test_a_run_that_never_started_reports_the_config_error_and_the_drivers_own_words(
    fake_chief, monkeypatch
):
    monkeypatch.setenv("FAKE_CHIEF_STDOUT", "")
    monkeypatch.setenv("FAKE_CHIEF_STDERR", "chief: another driver is already active\n")
    monkeypatch.setenv("FAKE_CHIEF_EXIT", "2")

    run = run_tasklists([UNIT.name])

    assert run.outcome == "config-error" and run.exit_code == 2
    assert run.run_id == "" and run.tasklists == ()


def test_a_missing_driver_is_named_not_guessed_at(monkeypatch, tmp_path):
    monkeypatch.setenv(headless.CHIEF_BIN_ENV, str(tmp_path / "nope"))
    monkeypatch.setenv(headless.PRESET_ENDPOINT, ENDPOINT)
    monkeypatch.setenv(headless.PRESET_MODEL, MODEL)

    with pytest.raises(HeadlessError) as excinfo:
        run_tasklists([UNIT.name])

    assert "could not start the driver" in str(excinfo.value)


def test_naming_no_tasklist_is_refused():
    with pytest.raises(HeadlessError):
        run_tasklists([], preset=LocalPreset(endpoint=ENDPOINT, model=MODEL))


# --- the units it drives -----------------------------------------------------


def test_a_missing_tasklist_is_generated_and_an_existing_one_is_left_alone(tmp_path):
    path = ensure_tasklist(UNIT, root=tmp_path)

    doc = json.loads(path.read_text())
    assert doc["branchName"] == f"chief/{UNIT.name}"
    assert tasklists.tasklist_failures(doc, name=UNIT.name) == []

    # Chief owns this document once it is in flight: its `passes` flags are bookkeeping,
    # so a second call must not regenerate over them.
    doc["userStories"][0]["passes"] = True
    path.write_text(json.dumps(doc))
    assert ensure_tasklist(UNIT, root=tmp_path) == path
    assert json.loads(path.read_text())["userStories"][0]["passes"] is True


def test_run_units_writes_what_is_missing_then_drives_the_lot(fake_chief, tmp_path):
    run = run_units([UNIT], root=tmp_path)

    assert (tmp_path / "tasks/chief" / f"{UNIT.name}.json").is_file()
    assert fake_chief()["argv"][-1] == UNIT.name
    assert fake_chief()["cwd"] == str(tmp_path)
    assert run.ok


def test_units_are_resolved_against_the_live_library():
    units = headless.units_for([a_unit_with_work().name])

    assert units and units[0].command.startswith("python3 -m praxis.")
    with pytest.raises(TasklistError):
        headless.units_for([])


# --- the CLI -----------------------------------------------------------------


def test_the_plan_reports_the_argv_and_spawns_nothing(capsys, monkeypatch):
    monkeypatch.setenv(headless.PRESET_ENDPOINT, ENDPOINT)
    monkeypatch.setenv(headless.PRESET_MODEL, MODEL)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned"))

    assert headless.main(["plan", a_unit_with_work().name]) == 0

    out = capsys.readouterr().out
    assert "--headless" in out and f"--preset={headless.PRESET}" in out
    assert MODEL in out and ENDPOINT in out


def test_the_plan_names_what_the_preset_is_missing(capsys, monkeypatch):
    for name in (headless.PRESET_ENDPOINT, headless.PRESET_MODEL):
        monkeypatch.delenv(name, raising=False)

    assert headless.main(["plan", a_unit_with_work().name]) == 0

    assert headless.PRESET_ENDPOINT in capsys.readouterr().out


def test_the_cli_exits_with_chiefs_own_code_and_points_at_the_remainder(
    fake_chief, capsys, monkeypatch, tmp_path
):
    # The CLI resolves `tasks/chief` off the repo root; point that at a tmp dir so the
    # test cannot generate a tasklist into the working tree.
    monkeypatch.setattr(tasklists, "repo_root", lambda: tmp_path)
    name = a_unit_with_work().name
    monkeypatch.setenv("FAKE_CHIEF_STDOUT", contract_lines(
        outcome="verify-failed", exit_code=4,
        tasklists_rows=[row(name, "verify-failed")]))
    monkeypatch.setenv("FAKE_CHIEF_EXIT", "4")

    code = headless.main(["run", name])

    out = capsys.readouterr().out
    assert code == 4
    assert "verify-failed" in out
    assert f"python3 -m praxis.headless run {name}" in out
    assert "resumed pass" in out


def test_an_unknown_unit_is_reported_by_the_cli(capsys):
    assert headless.main(["run", "gate-nonesuch"]) == 2

    assert "gate-nonesuch" in capsys.readouterr().err


# --- the documentation the mode ships with -----------------------------------


DOC = ROOT / "docs/reference/chief-powered-construction.md"


def test_the_mode_is_documented_and_linked_from_the_map():
    assert DOC.is_file()
    text = DOC.read_text()

    # what it drives, the two cross-repo contracts, and the tradeoff taken knowingly
    assert "praxis.backfill" in text and "praxis.construct" in text
    assert "chief:80-headless-programmatic-invocation" in text
    assert "chief:82-local-inference-cost-avoidance-preset" in text
    assert "--headless" in text and "--preset local" in text
    assert headless.PRESET_ENDPOINT in text and headless.PRESET_MODEL in text
    for phrase in ("tradeoff", "skip-if-", "resum"):
        assert phrase in text.lower() or phrase in text

    readme = (ROOT / "docs/README.md").read_text()
    assert "reference/chief-powered-construction.md" in readme


def test_the_wiring_calls_no_model_of_its_own():
    """`praxis/llm.py` is not this module's dependency — the agent chief runs is."""
    source = (ROOT / "praxis/headless.py").read_text()

    assert "praxis.llm" not in source and "import llm" not in source
    assert "ANTHROPIC_API_KEY" not in source and "OPENAI_API_KEY" not in source

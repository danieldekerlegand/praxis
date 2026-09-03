"""Chief tasklists for praxis batch work: a unit of the live library in, a tasklist out.

The generator writes no notebook and no gate — it emits the JSON Chief runs — so what is
asserted here is the document and the selection behind it: that a generated tasklist is
valid JSON with the fields chief's schema requires (`chief/<name>`, `passes: false`, no
`mergedToMain`, a category `scripts/check-tasklist-categories.mjs` accepts), that it
targets the *real* backlog of a real domain or subject, that a unit with nothing to do
never becomes a run, and that the command the stories name actually exists and can be
run with no key configured.

No test touches the network or a model.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import curriculum  # noqa: E402
from curriculum import save_subject, subject_from_dict  # noqa: E402
from praxis import backfill, suggestion_review, tasklist  # noqa: E402
from praxis.construct import construct_topic  # noqa: E402
from praxis.tasklist import (  # noqa: E402
    CATEGORIES,
    TasklistError,
    Unit,
    accepted_units,
    backfill_unit,
    library_units,
    subject_unit,
    tasklist_failures,
    unit_for,
    write_tasklist,
)
from scaffold_notebooks import scaffold_subject  # noqa: E402
from test_backfill import domain, subjects_root  # noqa: E402, F401
from test_construct import FakeClient, good_cells  # noqa: E402
from test_construct import reply as cell_reply  # noqa: E402


# A unit whose *shape* is under test needs no notebooks on disk — only the selection
# tests below need a real library. Built to match a real seed domain so the document
# they grade is the one the generator emits.
UNIT = Unit(
    name="gate-01-symbolic-ai-logic",
    kind="backfill",
    slug="01-symbolic-ai-logic",
    title="Symbolic AI & Logic",
    command="python3 -m praxis.backfill 01-symbolic-ai-logic",
    pending=("01-symbolic-ai-logic/datalog.ipynb", "01-symbolic-ai-logic/sparql.ipynb"),
    done=3,
    touches=("notebooks/01-symbolic-ai-logic",),
    category="fix",
)


# --- what a unit selects -----------------------------------------------------


def test_a_backfill_unit_targets_the_domains_real_ungated_notebooks(domain):
    module, subject = domain

    unit = backfill_unit(module, subject=subject)

    # `traits` is the ✅-but-ungated one; `ownership` is gated, `wiring` is a scaffold.
    assert unit.pending == (f"{module.dir}/traits.ipynb",)
    assert unit.done == 1
    assert unit.kind == "backfill"
    assert unit.command == f"python3 -m praxis.backfill {module.dir}"
    assert unit.branch == f"chief/{unit.name}"


def test_the_selection_is_backfill_targets_and_nothing_else(domain):
    """The tasklist promises exactly what the command it names will pick up."""
    module, subject = domain

    unit = backfill_unit(module, subject=subject)

    targets = backfill.backfill_targets(module, subject=subject)
    assert unit.pending == tuple(f"{d.dir}/{t.slug}.ipynb" for d, t, _ in targets)


def test_a_subject_unit_is_wider_than_a_backfill(domain):
    """A subject arrives unbuilt, so its unit covers construction as well as gating."""
    _, subject = domain

    unit = subject_unit(subject)

    assert unit.kind == "subject"
    assert [rel.rsplit("/", 1)[-1] for rel in unit.pending] == ["traits.ipynb", "wiring.ipynb"]
    assert unit.done == 1
    assert unit.command == f"python3 -m praxis.construct --subject {subject.slug}"
    assert unit.touches == (f"subjects/{subject.slug}",)


def test_every_seed_domain_offers_a_unit_and_they_agree_with_the_coverage_count():
    units = {u.slug: u for u in library_units()}

    assert set(units) == {d.dir for d in curriculum.DOMAINS}
    for dom, gated, complete, _total in backfill.coverage():
        assert units[dom.dir].done == gated
        assert len(units[dom.dir].pending) == complete - gated


def test_a_seed_domain_with_nothing_left_to_do_never_becomes_a_run():
    """An empty tasklist is a Chief run spent proving the library was already gated."""
    finished = [u for u in library_units() if not u.pending]
    if not finished:
        pytest.skip("every seed domain still has an ungated notebook")

    with pytest.raises(TasklistError, match="nothing to do"):
        unit_for(finished[0].name)


def test_a_fully_gated_subject_is_refused_by_name(subjects_root):
    subject = subject_from_dict(
        {"title": "Finished", "blurb": "b", "modules": [
            {"title": "M", "blurb": "b", "topics": [{"title": "One", "slug": "one"}]}]},
        goal="finish something",
    )
    save_subject(subject)
    scaffold_subject(subject)
    module = subject.modules[0]
    construct_topic(module, module.topics[0], client=FakeClient(cell_reply(good_cells())))

    assert subject_unit(subject).pending == ()
    with pytest.raises(TasklistError, match="nothing to do"):
        unit_for(f"build-{subject.slug}")


def test_an_unknown_unit_names_how_units_are_named():
    with pytest.raises(TasklistError, match="gate-<domain-dir>"):
        unit_for("gate-nothing-like-this")


# --- what the generated tasklist looks like ----------------------------------


def test_a_generated_tasklist_is_well_formed():
    unit = UNIT

    doc = tasklist.tasklist(unit)

    assert tasklist_failures(doc, name=unit.name) == []
    assert doc["project"] == "praxis"
    assert doc["branchName"] == f"chief/{unit.name}"
    assert doc["baseBranch"] == "main"
    assert doc["category"] in CATEGORIES
    assert "mergedToMain" not in doc
    assert doc["userStories"] and all(s["passes"] is False for s in doc["userStories"])
    assert doc["touches"] == ["notebooks/01-symbolic-ai-logic"]
    assert doc["iters"] >= tasklist.MIN_ITERS


def test_the_stories_name_the_shipped_command_and_the_resumability_contract():
    unit = UNIT

    doc = tasklist.tasklist(unit)

    text = json.dumps(doc)
    assert unit.command in text                      # it drives the shipped loop...
    assert "write no new construction or gating code" in text   # ...and nothing else
    resume = doc["userStories"][1]
    assert "skipped by construct_topic" in " ".join(resume["acceptanceCriteria"])
    assert "already-gated topic is not a target" in " ".join(resume["acceptanceCriteria"])


def test_every_criterion_is_satisfiable_from_the_worktree():
    """A criterion naming another repo fails a Chief run UNSATISFIABLE before it starts."""
    doc = tasklist.tasklist(UNIT)

    for story in doc["userStories"]:
        for criterion in story["acceptanceCriteria"]:
            assert "../" not in criterion
            assert not any(f"{repo}:" in criterion for repo in ("chief", "agora", "koine"))


def test_iters_scales_with_the_backlog_between_its_bounds():
    def iters(n: int) -> int:
        return tasklist.tasklist(Unit("gate-x", "backfill", "x", "X", "cmd",
                                      tuple(f"x/{i}.ipynb" for i in range(n)), 0,
                                      ("notebooks/x",), "fix"))["iters"]

    assert iters(1) == tasklist.MIN_ITERS
    assert iters(5) < iters(30)
    assert iters(500) == tasklist.MAX_ITERS


# --- the grader --------------------------------------------------------------


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.update(branchName="feature/x"), "chief/"),
    (lambda d: d.update(category="content"), "category"),
    (lambda d: d.update(project="other"), "project"),
    (lambda d: d.update(mergedToMain="abc1234"), "mergedToMain"),
    (lambda d: d["userStories"][0].update(passes=True), "passes"),
    (lambda d: d["userStories"][0].update(acceptanceCriteria=[]), "acceptance criteria"),
    (lambda d: d["userStories"][1].update(id="US-1"), "used twice"),
    (lambda d: d.update(userStories=[]), "userStories"),
    (lambda d: d.update(iters=0), "iters"),
    (lambda d: d.update(touches="notebooks/x"), "touches"),
])
def test_the_grader_names_what_is_wrong(mutate, expected):
    doc = tasklist.tasklist(UNIT)

    mutate(doc)

    failures = tasklist_failures(doc)
    assert failures, f"expected a failure mentioning {expected!r}"
    assert any(expected in failure for failure in failures)


def test_the_category_vocabulary_matches_the_repo_wide_guard():
    """`scripts/check-tasklist-categories.mjs` is what a generated tasklist must clear."""
    source = (ROOT / "scripts" / "check-tasklist-categories.mjs").read_text()
    declared = source.split("const CATEGORIES = ", 1)[1].split(";", 1)[0]

    assert sorted(json.loads(declared.replace("'", '"'))) == sorted(CATEGORIES)


# --- writing it --------------------------------------------------------------


def test_a_written_tasklist_is_valid_json_on_disk(tmp_path):
    unit = UNIT

    path = write_tasklist(unit, root=tmp_path)

    assert path == tmp_path / "tasks" / "chief" / f"{unit.name}.json"
    doc = json.loads(path.read_text())
    assert tasklist_failures(doc, name=unit.name) == []
    if shutil.which("jq"):  # the criterion's own check, when the tool is here
        assert subprocess.run(["jq", "-e", "."], stdin=path.open(),
                              stdout=subprocess.DEVNULL).returncode == 0


def test_a_tasklist_that_fails_the_grader_is_never_written(tmp_path, monkeypatch):
    """The constructor's rule, one level up: what fails the grader does not land."""
    monkeypatch.setattr(tasklist, "tasklist", lambda unit: {"project": "praxis",
                                                            "userStories": []})

    with pytest.raises(TasklistError, match="not well-formed"):
        write_tasklist(UNIT, root=tmp_path)

    assert not (tmp_path / "tasks" / "chief").exists()


def test_an_active_or_retired_tasklist_is_not_overwritten(tmp_path):
    unit = UNIT
    path = write_tasklist(unit, root=tmp_path)
    path.write_text(json.dumps({"in": "flight"}))

    with pytest.raises(TasklistError, match="already active"):
        write_tasklist(unit, root=tmp_path)
    assert json.loads(path.read_text()) == {"in": "flight"}

    write_tasklist(unit, root=tmp_path, force=True)          # ...unless asked
    assert tasklist_failures(json.loads(path.read_text()), name=unit.name) == []

    path.unlink()
    retired = tmp_path / "tasks" / "chief" / "completed" / f"{unit.name}.json"
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text(json.dumps({"mergedToMain": "abc1234"}))
    with pytest.raises(TasklistError, match="retired"):
        write_tasklist(unit, root=tmp_path)


# --- the JD half -------------------------------------------------------------


def test_accepted_suggestions_become_subject_units(domain):
    _, subject = domain
    suggestion_review.save("posting-1", {
        "jd": "posting-1", "suggestions": [],
        "accepted": [{"id": "rust", "slug": subject.slug}],
    })

    (unit,) = accepted_units("posting-1")

    assert unit.name == f"build-{subject.slug}"
    assert unit.command == f"python3 -m praxis.construct --subject {subject.slug}"


def test_an_accepted_slug_with_no_subject_on_disk_is_reported_not_guessed(domain):
    suggestion_review.save("posting-2", {
        "jd": "posting-2", "accepted": [{"id": "gone", "slug": "no-such-subject"}],
    })

    with pytest.raises(TasklistError, match="no-such-subject"):
        accepted_units("posting-2")


def test_a_posting_with_nothing_accepted_is_not_a_tasklist():
    suggestion_review.save("posting-3", {"jd": "posting-3", "accepted": []})

    with pytest.raises(TasklistError, match="accept a suggestion first"):
        accepted_units("posting-3")


# --- the command the stories name --------------------------------------------


def test_the_command_a_tasklist_names_exists_and_costs_no_key(capsys):
    """`--list` is the plan: the selection, printed with no model call and no key."""
    dom = curriculum.DOMAINS[0]

    code = backfill.main(["--list", dom.dir])

    assert code == 0
    out = capsys.readouterr().out
    assert dom.dir in out
    assert "topics selected" in out


def test_the_backfill_cli_names_the_domain_id_when_it_is_wrong(capsys):
    assert backfill.main(["--list", "notebooks/01-symbolic-ai-logic"]) == 2
    assert "no seed domain" in capsys.readouterr().err

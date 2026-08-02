"""Storage: where a user's own data lives, and that it is still there afterwards.

The claim this file has to actually hold up is the boring one — *it persists*. So the
round-trip test does not stub a filesystem or trust an in-process cache: it writes a
subject, a notebook and a learner's progress, then reads them back from a **separate
Python process** given nothing but the environment the app would give it. That is what
"survives a restart" means, and it is the only version of it worth asserting.
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
from curriculum import save_subject, subject_from_dict, subjects_dir  # noqa: E402
from praxis import storage  # noqa: E402
from praxis.checks import CheckOutcome  # noqa: E402
from praxis.progress import load_progress, progress_dir, record_outcome  # noqa: E402

CURRICULUM = {
    "title": "Coastal Navigation",
    "blurb": "Get off the dock and back again.",
    "modules": [
        {"title": "Charts", "topics": [{"title": "Reading a Chart"}]},
    ],
}

REL = "subjects/coastal-navigation/01-charts/reading-a-chart.ipynb"


@pytest.fixture(autouse=True)
def own_storage(monkeypatch, app_dir):
    """This module tests the defaults, so the per-leaf overrides must be out of the way."""
    monkeypatch.delenv("PRAXIS_SUBJECTS_DIR", raising=False)
    monkeypatch.delenv("PRAXIS_PROGRESS_DIR", raising=False)
    return app_dir


# --- where the data lands ---------------------------------------------------


def test_the_app_directory_follows_the_environment(app_dir):
    assert storage.app_dir() == app_dir
    assert storage.config_path() == app_dir / "storage.json"


def test_the_platform_default_is_the_one_tauri_would_hand_us(monkeypatch):
    """No environment at all: the same per-OS app-data path as the shell's identifier."""
    monkeypatch.delenv("PRAXIS_APP_DIR", raising=False)
    assert storage.app_dir().name == storage.APP_ID
    assert storage.app_dir().is_absolute()


def test_the_shell_identifier_and_the_python_side_agree():
    conf = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())
    assert conf["identifier"] == storage.APP_ID


def test_the_documented_layout_is_the_one_on_disk(app_dir):
    """subjects/ and progress/ under one root — the layout docs/storage.md describes."""
    root = app_dir / "data"
    assert storage.data_root() == root
    assert storage.subjects_dir() == root / "subjects"
    assert storage.progress_dir() == root / "progress"
    # and the modules that write them agree, because they delegate here
    assert subjects_dir() == storage.subjects_dir()
    assert progress_dir() == storage.progress_dir()


def test_the_seed_library_is_not_user_data(app_dir):
    """`notebooks/` ships with the app; nothing under the storage root shadows it."""
    assert curriculum.NOTEBOOKS_DIR == ROOT / "notebooks"
    assert app_dir not in curriculum.NOTEBOOKS_DIR.parents


def test_the_leaf_overrides_still_win(monkeypatch, tmp_path):
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("PRAXIS_PROGRESS_DIR", str(tmp_path / "other"))
    assert subjects_dir() == tmp_path / "elsewhere"
    assert progress_dir() == tmp_path / "other"


def test_the_app_root_is_relocatable_on_its_own(monkeypatch, tmp_path):
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "portable"))
    assert storage.data_root() == tmp_path / "portable"
    assert subjects_dir() == tmp_path / "portable" / "subjects"


# --- the backend abstraction ------------------------------------------------


def test_app_storage_is_the_default_backend():
    backend = storage.active_backend()
    assert backend.kind == "app"
    assert backend.available() == (True, "")
    assert storage.kinds()[0] == "app"


def test_ensure_creates_the_layout(app_dir):
    root = storage.active_backend().ensure()
    assert (root / "subjects").is_dir() and (root / "progress").is_dir()


def test_an_unwritable_root_is_reported_not_raised(monkeypatch, tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(blocked))
    ok, why = storage.active_backend().available()
    assert not ok and "not a directory" in why
    with pytest.raises(storage.StorageError):
        storage.active_backend().ensure()


def test_an_unknown_backend_falls_back_instead_of_locking_the_user_out(app_dir):
    storage.save_config({"active": "quantum-tape", "backends": {}})
    backend = storage.active_backend()
    assert backend.kind == "app"
    assert "quantum-tape" in backend.detail


def test_a_corrupt_config_costs_the_selection_never_the_data(app_dir):
    app_dir.mkdir(parents=True, exist_ok=True)
    storage.config_path().write_text("{ not json")
    assert storage.load_config() == storage.default_config()
    assert storage.active_backend().kind == "app"


def test_selecting_a_backend_persists_and_verifies_it(app_dir):
    backend = storage.select_backend("app")
    assert backend.root.is_dir()
    assert json.loads(storage.config_path().read_text())["active"] == "app"
    with pytest.raises(storage.StorageError, match="unknown storage backend"):
        storage.select_backend("floppy")


def test_a_registered_backend_needs_no_change_to_any_caller(monkeypatch, tmp_path):
    """The plug point: a resolver and (optionally) an availability check, nothing else."""
    elsewhere = tmp_path / "plugged-in"
    monkeypatch.setitem(
        storage._RESOLVERS,
        "test-kind",
        lambda opts: storage.Backend(
            kind="test-kind", root=elsewhere, label="a test backend", options=dict(opts)
        ),
    )
    storage.select_backend("test-kind", {"note": "hello"})
    assert subjects_dir() == elsewhere / "subjects"
    assert progress_dir() == elsewhere / "progress"
    assert storage.active_backend().options == {"note": "hello"}


def test_credentials_never_reach_a_client(monkeypatch, tmp_path):
    monkeypatch.setitem(
        storage._RESOLVERS,
        "test-kind",
        lambda opts: storage.Backend(
            kind="test-kind", root=tmp_path / "b", label="test", options=dict(opts)
        ),
    )
    storage.select_backend("test-kind", {"bucket": "praxis", "secret_key": "s3kr1t"})
    described = storage.describe()
    assert described["options"] == {"bucket": "praxis"}
    assert "s3kr1t" not in json.dumps(described)


def test_describe_reports_the_whole_picture(app_dir):
    described = storage.describe()
    assert described["kind"] == "app"
    assert described["appDir"] == str(app_dir)
    assert described["subjects"] == str(subjects_dir())
    assert described["available"] is True


# --- the claim that matters: it is still there after a restart --------------


RESTART = """
import json, sys
sys.path.insert(0, {root!r})
from curriculum import load_subject
from praxis.progress import load_progress
from praxis import storage

subject = load_subject("coastal-navigation")
print(json.dumps({{
    "root": str(storage.data_root()),
    "title": subject.title,
    "topics": [t.title for m in subject.modules for t in m.topics],
    "notebook": (storage.subjects_dir() / {rel!r}).read_text(),
    "outcomes": load_progress("ada")["topics"][{topic!r}]["outcomes"],
}}))
"""


def test_a_written_subject_and_its_progress_survive_a_restart(app_dir, tmp_path):
    """Write it here, read it back out of a brand-new interpreter. No shared state."""
    subject = subject_from_dict(CURRICULUM, goal="sail the coast")
    save_subject(subject)
    notebook = subjects_dir() / "coastal-navigation" / "01-charts" / "reading-a-chart.ipynb"
    notebook.parent.mkdir(parents=True, exist_ok=True)
    notebook.write_text('{"cells": []}')
    record_outcome(
        "ada",
        REL,
        CheckOutcome(
            check_id="charts-1",
            kind="choice",
            section="Concepts",
            passed=True,
            answer="a rhumb line",
        ),
    )

    script = RESTART.format(
        root=str(ROOT),
        rel="coastal-navigation/01-charts/reading-a-chart.ipynb",
        topic=REL,
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),  # a different cwd too: nothing may depend on where it ran
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PRAXIS_APP_DIR": str(app_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    read_back = json.loads(proc.stdout)

    assert read_back["root"] == str(app_dir / "data")
    assert read_back["title"] == "Coastal Navigation"
    assert read_back["topics"] == ["Reading a Chart"]
    assert read_back["notebook"] == '{"cells": []}'
    assert read_back["outcomes"]["charts-1"]["passed"] is True
    assert read_back["outcomes"]["charts-1"]["answer"] == "a rhumb line"


def test_a_restart_reads_the_same_files_this_process_wrote(app_dir):
    """The in-process half of the same claim — load_progress re-reads, never caches."""
    record_outcome("ada", REL, CheckOutcome("c1", "code", "Practice", True, "assert True"))
    assert load_progress("ada")["topics"][REL]["outcomes"]["c1"]["passed"] is True
    assert (progress_dir() / "ada.json").is_file()

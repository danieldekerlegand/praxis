"""The other two places a user's work can live: a mounted drive, and a bucket.

`tests/test_storage.py` covers the default backend and the layout. This file is about the
claims US-2 makes that are easy to fake and expensive to get wrong:

* selecting a backend actually moves where every writer writes — checked through
  `curriculum.save_subject` and `praxis.progress.record_outcome`, not by reading
  `storage.subjects_dir()` back;
* the data is still there after a restart, read by a **separate interpreter** that is
  given nothing but the environment the app would give it;
* a backend that has gone away (a drive unplugged, a bucket unreachable) produces a clear
  message and *refuses the write*, rather than silently recreating the drive's folder on
  the internal disk;
* the cloud round trip is a real one. `tests/mocks3.py` serves the S3 protocol on a
  loopback port, so `praxis/s3.py` signs and sends the requests it would send to AWS.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mocks3 import MockS3  # noqa: E402
from curriculum import save_subject, subject_from_dict  # noqa: E402
from praxis import cloud, storage  # noqa: E402
from praxis.checks import CheckOutcome  # noqa: E402
from praxis.progress import record_outcome  # noqa: E402
from praxis.s3 import S3Client, S3Error  # noqa: E402

CURRICULUM = {
    "title": "Coastal Navigation",
    "blurb": "Get off the dock and back again.",
    "modules": [{"title": "Charts", "topics": [{"title": "Reading a Chart"}]}],
}
REL = "subjects/coastal-navigation/01-charts/reading-a-chart.ipynb"
NOTEBOOK = "coastal-navigation/01-charts/reading-a-chart.ipynb"


@pytest.fixture(autouse=True)
def own_storage(monkeypatch, app_dir):
    """These tests are about the backends themselves, so the leaf overrides must be off."""
    monkeypatch.delenv("PRAXIS_SUBJECTS_DIR", raising=False)
    monkeypatch.delenv("PRAXIS_PROGRESS_DIR", raising=False)
    return app_dir


@pytest.fixture
def s3():
    server = MockS3()
    try:
        yield server
    finally:
        server.stop()


def write_a_subject_and_some_progress() -> None:
    """One of each of the four writes, through the modules that really do them."""
    save_subject(subject_from_dict(CURRICULUM, goal="sail the coast"))
    notebook = storage.subjects_dir() / NOTEBOOK
    notebook.parent.mkdir(parents=True, exist_ok=True)
    notebook.write_text('{"cells": []}')
    (notebook.parent / "reading-a-chart.checks.json").write_text('{"checks": []}')
    record_outcome("ada", REL, CheckOutcome("charts-1", "choice", "Concepts", True, "a rhumb"))


RESTART = """
import json, sys
sys.path.insert(0, {root!r})
from curriculum import load_subject
from praxis.progress import load_progress
from praxis import storage

print(json.dumps({{
    "kind": storage.active_backend().kind,
    "root": str(storage.data_root()),
    "title": load_subject("coastal-navigation").title,
    "notebook": (storage.subjects_dir() / {nb!r}).read_text(),
    "passed": load_progress("ada")["topics"][{rel!r}]["outcomes"]["charts-1"]["passed"],
}}))
"""


def read_it_back_in_a_new_process(app_dir: Path, home: Path, extra: dict | None = None) -> dict:
    """What a restart sees: a fresh interpreter, a different cwd, only the app's env."""
    home.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-c", RESTART.format(root=str(ROOT), nb=NOTEBOOK, rel=REL)],
        capture_output=True,
        text=True,
        cwd=str(home),
        env={"PATH": "/usr/bin:/bin", "HOME": str(home),
             "PRAXIS_APP_DIR": str(app_dir), **(extra or {})},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- the mounted drive ------------------------------------------------------


def test_a_drive_is_the_folder_the_user_picked_verbatim(tmp_path):
    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    backend = storage.select_backend("drive", {"path": str(drive)})
    assert backend.kind == "drive"
    assert backend.root == drive
    assert (drive / "subjects").is_dir() and (drive / "progress").is_dir()


def test_selecting_a_drive_moves_every_writer_onto_it(tmp_path):
    """Not asserted through subjects_dir() — through the modules that write."""
    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    storage.select_backend("drive", {"path": str(drive)})
    write_a_subject_and_some_progress()

    assert (drive / "subjects" / "coastal-navigation" / "curriculum.json").is_file()
    assert (drive / "subjects" / NOTEBOOK).is_file()
    assert (drive / "progress" / "ada.json").is_file()


def test_a_drives_work_survives_a_restart(app_dir, tmp_path):
    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    storage.select_backend("drive", {"path": str(drive)})
    write_a_subject_and_some_progress()

    read_back = read_it_back_in_a_new_process(app_dir, tmp_path / "elsewhere-home")
    assert read_back["kind"] == "drive"
    assert read_back["root"] == str(drive)
    assert read_back["title"] == "Coastal Navigation"
    assert read_back["notebook"] == '{"cells": []}'
    assert read_back["passed"] is True


def test_an_unplugged_drive_says_so_instead_of_reappearing_on_the_internal_disk(tmp_path):
    """The failure this check exists for: the mount is gone but its *parent* isn't.

    `/Volumes` outlives the disk that was mounted under it, so a check that walked up to
    the first existing ancestor would find one, create the folder there and let the user
    fill a decoy. The immediate parent has to be the thing that is present.
    """
    mount = tmp_path / "Backup"
    drive = mount / "Praxis"
    mount.mkdir()
    storage.select_backend("drive", {"path": str(drive)})
    assert storage.active_backend().available() == (True, "")

    mount.rename(tmp_path / "Backup-unplugged")  # pull the disk out

    ok, why = storage.active_backend().available()
    assert not ok
    assert str(mount) in why and "mounted" in why
    assert not drive.exists()
    assert storage.active_backend().writable()[0] is False
    with pytest.raises(storage.StorageError):
        storage.active_backend().ensure()


def test_a_drive_that_was_never_there_is_refused_and_the_old_one_survives(tmp_path):
    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    storage.select_backend("drive", {"path": str(drive)})

    with pytest.raises(storage.StorageError, match="is not there"):
        storage.select_backend("drive", {"path": str(tmp_path / "nope" / "deeper" / "P")})
    assert storage.active_backend().root == drive  # the selection did not move


def test_a_drive_with_no_folder_chosen_is_not_available():
    ok, why = storage.resolve("drive", {}).available()
    assert not ok and "pick one" in why


# --- the S3 client, against a real socket -----------------------------------


def test_the_s3_client_round_trips_an_object(s3):
    client = S3Client(**{k: v for k, v in {
        "endpoint": s3.endpoint, "bucket": "praxis",
        "access_key_id": "a", "secret_access_key": "b", "region": "us-east-1"}.items()})
    etag = client.put_object("hello/world.txt", b"contents")
    assert etag == "98bf7d8c15784f0a3d63204441e1e2aa"
    assert client.get_object("hello/world.txt") == b"contents"
    assert [o.key for o in client.list_objects()] == ["hello/world.txt"]
    client.delete_object("hello/world.txt")
    assert client.list_objects() == []


def test_the_s3_client_signs_its_requests(s3):
    """The mock rejects an unsigned request, so this fails if signing is skipped."""
    anonymous = S3Client(endpoint=s3.endpoint, bucket="praxis")
    with pytest.raises(S3Error, match="403"):
        anonymous.head_bucket()


def test_the_s3_client_follows_continuation_tokens(s3):
    client = cloud.client_for(s3.options())
    for i in range(7):
        client.put_object(f"k{i}", b"x")
    assert len(client.list_objects(max_keys=3)) == 7


def test_a_missing_bucket_is_an_error_with_the_reason(s3):
    with pytest.raises(S3Error, match="404"):
        cloud.client_for(s3.options(bucket="nope")).head_bucket()


# --- the cloud backend ------------------------------------------------------


def test_a_cloud_backend_mirrors_the_bucket_inside_the_app_directory(s3, app_dir):
    backend = storage.select_backend("cloud", s3.options(prefix="praxis/"))
    assert backend.kind == "cloud"
    assert backend.root == app_dir / "cloud" / "praxis-praxis"
    assert backend.root.is_dir()
    assert backend.available() == (True, "")


def test_writing_to_the_cloud_backend_and_syncing_puts_it_in_the_bucket(s3):
    storage.select_backend("cloud", s3.options(prefix="team/"))
    write_a_subject_and_some_progress()
    assert s3.keys() == []  # nothing leaves this machine until a sync says so

    result = storage.sync_active()
    assert result["synced"] is True
    assert s3.keys() == [
        "team/progress/ada.json",
        "team/subjects/coastal-navigation/01-charts/reading-a-chart.checks.json",
        "team/subjects/coastal-navigation/01-charts/reading-a-chart.ipynb",
        "team/subjects/coastal-navigation/curriculum.json",
    ]
    assert s3.body("team/subjects/" + NOTEBOOK) == b'{"cells": []}'


def test_a_second_sync_moves_nothing(s3):
    """Idempotent, and by content: the ETag comparison must not re-upload every file."""
    storage.select_backend("cloud", s3.options())
    write_a_subject_and_some_progress()
    storage.sync_active()
    uploaded = len(s3.puts)

    again = storage.sync_active()
    assert again["moved"] == 0
    assert len(s3.puts) == uploaded


def test_the_cloud_round_trip_survives_losing_the_mirror_and_the_process(s3, app_dir, tmp_path):
    """The claim: work written here, pushed, and then read back from the bucket alone.

    The mirror is deleted between the two halves, so nothing on this disk can be what the
    second process reads — it has to come down from the bucket, in a fresh interpreter.
    """
    backend = storage.select_backend("cloud", s3.options(prefix="team/"))
    write_a_subject_and_some_progress()
    storage.sync_active()

    for path in sorted(backend.root.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert not any(backend.root.rglob("*"))

    pulled = storage.sync_active()
    assert len(pulled["pulled"]) == 4
    read_back = read_it_back_in_a_new_process(app_dir, tmp_path / "elsewhere-home")
    assert read_back["kind"] == "cloud"
    assert read_back["root"] == str(backend.root)
    assert read_back["title"] == "Coastal Navigation"
    assert read_back["notebook"] == '{"cells": []}'
    assert read_back["passed"] is True


def test_selecting_a_bucket_pulls_what_is_already_in_it(s3, app_dir):
    """The second machine: choose the bucket, and the work is there without a sync."""
    storage.select_backend("cloud", s3.options(prefix="team/"))
    write_a_subject_and_some_progress()
    storage.sync_active()

    storage.select_backend("app")           # go away…
    mirror = app_dir / "cloud" / "praxis-team"
    for path in sorted(mirror.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()

    storage.select_backend("cloud", s3.options(prefix="team/"))   # …and come back
    assert (storage.subjects_dir() / NOTEBOOK).read_text() == '{"cells": []}'


def test_the_newer_copy_wins_in_both_directions(s3, app_dir, tmp_path):
    storage.select_backend("cloud", s3.options())
    write_a_subject_and_some_progress()
    storage.sync_active()
    notebook = storage.subjects_dir() / NOTEBOOK

    # ours is newer -> the bucket takes it
    notebook.write_text('{"cells": ["local"]}')
    storage.sync_active()
    assert s3.body("subjects/" + NOTEBOOK) == b'{"cells": ["local"]}'

    # theirs is newer -> we take it back
    s3.buckets["praxis"].put("subjects/" + NOTEBOOK, b'{"cells": ["remote"]}',
                             time.time() + 60)
    storage.sync_active()
    assert notebook.read_text() == '{"cells": ["remote"]}'


def test_a_sync_never_deletes(s3):
    """A cleared bucket must not empty the mirror, and vice versa — work is only removed
    where the user removed it."""
    storage.select_backend("cloud", s3.options())
    write_a_subject_and_some_progress()
    storage.sync_active()

    s3.buckets["praxis"].objects.clear()
    storage.sync_active()
    assert (storage.subjects_dir() / NOTEBOOK).is_file()
    assert "subjects/" + NOTEBOOK in s3.keys()


def test_an_unreachable_bucket_is_a_clear_error_and_never_a_lost_notebook(s3, app_dir):
    """Offline: *not available* (no sync), still *writable* (the mirror is right here)."""
    backend = storage.select_backend("cloud", s3.options())
    write_a_subject_and_some_progress()
    s3.stop()

    ok, why = storage.active_backend().available()
    assert not ok
    assert "cannot reach" in why and "s3://praxis" in why
    assert storage.active_backend().writable() == (True, "")
    assert (storage.subjects_dir() / NOTEBOOK).is_file()

    with pytest.raises(storage.StorageError, match="cannot reach"):
        storage.sync_active()
    assert storage.active_backend().root == backend.root  # still selected, still there


def test_an_unreachable_bucket_cannot_be_selected(s3):
    endpoint = s3.endpoint
    s3.stop()
    with pytest.raises(storage.StorageError, match="cannot reach"):
        storage.select_backend("cloud", {"endpoint": endpoint, "bucket": "praxis"})
    assert storage.active_backend().kind == "app"


def test_a_cloud_backend_with_no_bucket_says_what_is_missing():
    ok, why = storage.resolve("cloud", {}).available()
    assert not ok and why == "no bucket configured"


# --- what the settings form is given ----------------------------------------


def test_the_secret_survives_editing_the_rest_of_the_form(s3):
    """The form is never sent the secret, so a blank one has to mean "keep it"."""
    storage.select_backend("cloud", s3.options(prefix="one/"))
    storage.select_backend("cloud", {**s3.options(prefix="two/"), "secret_access_key": ""})
    assert storage.active_backend().options["secret_access_key"] == "praxis-test-secret"
    assert storage.active_backend().options["prefix"] == "two/"


def test_the_secret_never_leaves_the_process(s3):
    storage.select_backend("cloud", s3.options())
    described = storage.describe()
    assert "praxis-test-secret" not in json.dumps(described)
    field = next(f for b in described["backends"] if b["kind"] == "cloud"
                 for f in b["fields"] if f["key"] == "secret_access_key")
    assert field["value"] == "" and field["set"] is True


def test_describe_offers_every_backend_and_its_fields(app_dir):
    described = storage.describe()
    assert [b["kind"] for b in described["backends"]] == storage.kinds()
    assert described["syncable"] is False
    drive = next(b for b in described["backends"] if b["kind"] == "drive")
    assert [f["key"] for f in drive["fields"]] == ["path"]
    assert all(b["blurb"] for b in described["backends"])


def test_a_backend_switch_leaves_the_old_root_alone(tmp_path):
    """Switching changes where Praxis looks; it does not move or delete anything."""
    write_a_subject_and_some_progress()
    app_root = storage.data_root()

    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    storage.select_backend("drive", {"path": str(drive)})
    assert not (drive / "subjects" / "coastal-navigation").exists()

    storage.select_backend("app")
    assert (app_root / "subjects" / NOTEBOOK).is_file()

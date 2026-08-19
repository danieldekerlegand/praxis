"""Importing a job description — the claims `praxis/jd.py` makes that are easy to fake.

The band's anti-fabrication rule is that a JD is "ingested" only when a **real** document
lands as normalized plain text on the active storage backend and reads back out. So the
fixtures in `tests/fixtures/jd/` are real files, not strings this suite made up:

    senior-platform-engineer.txt    the posting, written once
    senior-platform-engineer.md     the same posting as markdown
    senior-platform-engineer.docx   the same posting through `textutil -convert docx`
    senior-platform-engineer.pdf    the same posting printed by CUPS (`cupsfilter`)
    scanned-poster.pdf              an image turned into a PDF by `sips` — no text in it

Three of those are byte-different files carrying the same words, which is the strongest
statement available about a normalizer: `test_every_format_lands_on_one_canonical_text`
asserts the .txt, the .pdf and the .docx produce the **same string and the same id**. The
fifth is the failure a scan really is, from a real image, not a truncated PDF.

The round trip is read back by a **separate interpreter** given nothing but the
environment the app would give it, for the same reason `tests/test_storage_backends.py`
does it that way: an in-process read proves the object, not the file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import jd, storage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jd"
POSTING = "senior-platform-engineer"

#: Present in the posting whatever file it arrived as — the words a later band reads.
PHRASES = (
    "Senior Platform Engineer",
    "5+ years operating production systems on AWS or GCP.",
    "$185,000 - $225,000 base, plus equity.",
)


@pytest.fixture(autouse=True)
def own_storage(monkeypatch, app_dir):
    """This band's own leaf override off, so every test writes on the real backend."""
    monkeypatch.delenv("PRAXIS_JD_DIR", raising=False)
    return app_dir


def fixture(name: str) -> tuple[str, bytes]:
    path = FIXTURES / name
    return path.name, path.read_bytes()


def upload(name: str) -> dict:
    filename, data = fixture(name)
    return jd.ingest_upload(filename, data)


# --- parsing each format ----------------------------------------------------


@pytest.mark.parametrize("suffix,kind", [
    ("txt", "text"), ("md", "markdown"), ("pdf", "pdf"), ("docx", "docx"),
])
def test_each_supported_format_parses_to_the_posting(suffix, kind):
    doc = upload(f"{POSTING}.{suffix}")
    assert doc["kind"] == kind
    assert doc["mime"] == jd.MIMES[kind]
    assert doc["source"] == "upload"
    assert doc["filename"] == f"{POSTING}.{suffix}"
    assert doc["title"] == "Senior Platform Engineer"
    for phrase in PHRASES:
        # The markdown fixture writes the salary with an en dash, as markdown does.
        assert phrase in doc["text"] or phrase.replace(" - ", " – ") in doc["text"]
    assert doc["words"] > 150 and doc["chars"] == len(doc["text"])


def test_every_format_lands_on_one_canonical_text():
    """The point of the module: the file it arrived as stops mattering here."""
    docs = {s: upload(f"{POSTING}.{s}") for s in ("txt", "pdf", "docx")}
    texts = {s: d["text"] for s, d in docs.items()}
    assert texts["pdf"] == texts["txt"], "the PDF reader disagreed with the source text"
    assert texts["docx"] == texts["txt"], "the .docx reader disagreed with the source text"
    # Same text, so the same content digest, so one document rather than three.
    assert len({d["id"] for d in docs.values()}) == 1
    assert len(list(jd.jd_dir().glob("*.json"))) == 1


def test_pasted_text_is_the_same_document_as_the_uploaded_file():
    pasted = jd.ingest_text((FIXTURES / f"{POSTING}.txt").read_text())
    uploaded = upload(f"{POSTING}.txt")
    assert pasted["text"] == uploaded["text"]
    assert pasted["id"] == uploaded["id"]
    assert pasted["source"] == "paste" and pasted["filename"] == ""


def test_markdown_keeps_its_marks_but_the_title_does_not():
    doc = upload(f"{POSTING}.md")
    assert doc["text"].startswith("# Senior Platform Engineer")
    assert "## What you will do" in doc["text"]
    assert doc["title"] == "Senior Platform Engineer"


# --- normalizing ------------------------------------------------------------


def test_normalization_is_line_endings_spaces_and_blank_runs():
    messy = "﻿  Staff SRE \r\n\r\n\r\n\r\n Remote​ (EU)\t\r\n   \r\n"
    assert jd.normalize_text(messy) == "Staff SRE\n\n Remote (EU)"


def test_a_paste_with_nothing_in_it_is_refused_and_stores_nothing():
    with pytest.raises(jd.JDError) as exc:
        jd.ingest_text("   \n\n  ")
    assert "paste" in str(exc.value).lower()
    assert not list(jd.jd_dir().glob("*.json"))


def test_re_importing_the_same_posting_rewrites_one_document():
    """A user who is not sure the upload worked does it again. That is not two JDs."""
    first = upload(f"{POSTING}.txt")
    second = upload(f"{POSTING}.txt")
    assert first["id"] == second["id"]
    assert [p.name for p in jd.jd_dir().glob("*.json")] == [f"{first['id']}.json"]

    edited = jd.ingest_text((FIXTURES / f"{POSTING}.txt").read_text() + "\n\nEqual opportunity employer.")
    assert edited["id"] != first["id"]
    assert len(list(jd.jd_dir().glob("*.json"))) == 2


# --- what must not be stored ------------------------------------------------


def test_an_unsupported_format_names_the_ones_that_work():
    with pytest.raises(jd.JDError) as exc:
        jd.ingest_upload("posting.rtf", b"{\\rtf1 Senior Platform Engineer}")
    message = str(exc.value)
    assert ".rtf" in message and ".docx" in message and ".pdf" in message
    assert not list(jd.jd_dir().glob("*.json"))


def test_binary_that_is_not_a_document_is_refused_rather_than_mojibake():
    """CP1252 decodes any byte, so this has to be caught before the fallback."""
    png = (Path("/usr/share/doc/cups/images/color-wheel.png"))
    data = png.read_bytes() if png.is_file() else b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(400)
    with pytest.raises(jd.JDError) as exc:
        jd.ingest_upload("posting.txt", data)
    assert "not a text document" in str(exc.value)
    assert not list(jd.jd_dir().glob("*.json"))


def test_a_scanned_pdf_says_paste_the_text_instead():
    """A real image-only PDF: there is no text in it to find, and none is invented."""
    with pytest.raises(jd.JDError) as exc:
        upload("scanned-poster.pdf")
    assert "paste" in str(exc.value).lower()
    assert not list(jd.jd_dir().glob("*.json"))


def test_a_file_that_is_not_a_pdf_at_all_is_refused():
    with pytest.raises(jd.JDError) as exc:
        jd.ingest_upload("posting.pdf", b"Senior Platform Engineer, and no PDF header.")
    assert "%PDF" in str(exc.value)


def test_something_far_too_big_is_refused_before_it_is_decoded():
    with pytest.raises(jd.JDError) as exc:
        jd.ingest_upload("posting.txt", b"x" * (jd.MAX_BYTES + 1))
    assert "MB" in str(exc.value)
    assert not list(jd.jd_dir().glob("*.json"))


# --- storage ----------------------------------------------------------------


def test_the_document_lands_on_the_active_backend_never_in_the_repo(tmp_path):
    drive = tmp_path / "Backup" / "Praxis"
    drive.parent.mkdir(parents=True)
    storage.select_backend("drive", {"path": str(drive)})

    doc = upload(f"{POSTING}.pdf")

    assert jd.jd_dir() == drive / "jd" == storage.jd_dir()
    assert (drive / "jd" / f"{doc['id']}.json").is_file()
    assert not list(ROOT.glob("jd")), "a JD was written into the checkout"


def test_it_reads_back_off_the_backend_in_a_second_read():
    doc = upload(f"{POSTING}.docx")
    again = jd.load_jd(doc["id"])
    assert again == doc
    assert again["text"] == doc["text"]


def test_the_list_is_summaries_without_the_text():
    upload(f"{POSTING}.txt")
    upload(f"{POSTING}.md")
    listed = jd.list_jds()
    assert len(listed) == 2
    assert all("text" not in summary for summary in listed)
    assert {s["kind"] for s in listed} == {"text", "markdown"}
    assert all(s["words"] > 150 for s in listed)


READ_IT_BACK = """
import json, sys
sys.path.insert(0, {root!r})
from praxis import jd

doc = jd.load_jd({jd_id!r})
print(json.dumps({{
    "root": str(jd.jd_dir()),
    "text": doc["text"],
    "title": doc["title"],
    "llm_imported": "praxis.llm" in sys.modules,
}}))
"""


def test_a_restart_reads_the_same_text_back_and_needs_no_api_key(app_dir, tmp_path, monkeypatch):
    """The round trip, in a fresh interpreter with no key in its environment at all.

    Two claims at once, because they share a subprocess: the normalized text is really on
    the backend (not an object this test is still holding), and reading it back does not
    reach a model — `praxis.llm` is never imported by the JD path.
    """
    doc = upload(f"{POSTING}.pdf")
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        [sys.executable, "-c", READ_IT_BACK.format(root=str(ROOT), jd_id=doc["id"])],
        capture_output=True, text=True, cwd=str(home),
        env={"PATH": "/usr/bin:/bin", "HOME": str(home), "PRAXIS_APP_DIR": str(app_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    restarted = json.loads(proc.stdout)
    assert restarted["text"] == doc["text"]
    assert restarted["title"] == "Senior Platform Engineer"
    assert restarted["root"] == str(jd.jd_dir())
    assert restarted["llm_imported"] is False


def test_importing_needs_no_api_key(monkeypatch):
    """The read path is BYO-key-*optional*: plain text needs no model."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PRAXIS_API_KEY", "AGORA_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    assert upload(f"{POSTING}.docx")["words"] > 150


def test_a_utf16_export_is_text_not_binary():
    """UTF-16 is half NUL bytes, so the BOM has to be read before the binary check."""
    data = (FIXTURES / f"{POSTING}.txt").read_text().encode("utf-16")
    doc = jd.ingest_upload("posting.txt", data)
    assert doc["text"] == upload(f"{POSTING}.txt")["text"]

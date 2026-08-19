#!/usr/bin/env python3
"""Job descriptions — the front of the funnel, and the one thing the user brings.

Everything else in Praxis starts from a subject the user *types*. This starts from a
document they already have: the posting for the job they want. A JD is imported once,
normalized to **one canonical plain-text document**, and stored beside their subjects on
the active storage backend. Later bands read that text — what the role asks for, what
they can already do, which tutorials would close the gap — and every one of them reads
the same field, `doc["text"]`, whatever the file it arrived as.

So this module is a parser and a normalizer, and nothing else. In particular:

* **No model is called.** Plain text needs no model, and neither do the three formats
  below, so importing a JD works with no API key configured — the BYO-key requirement
  starts one band later, at extraction. `praxis/llm.py` is not imported here.
* **No parser is pulled in for a format that doesn't need one.** `.txt` and `.md` are a
  decode; `zipfile`/`xml` and `zlib` are imported *inside* the `.docx` and `.pdf`
  readers, so the paste path costs nothing and a Praxis that never sees a PDF never
  touches the PDF code.
* **Nothing that failed to parse is persisted.** An unsupported extension, a file that
  is not text, and a document that yields no words are each a `JDError` naming the file
  and what to do instead — never an empty document written under a hopeful id.

The four readers are stdlib only, in the same spirit as `praxis/s3.py` being `urllib`
and `hmac` rather than boto3:

    .txt / .md   decode (BOM-sniffed, then UTF-8, then CP1252), binary refused
    .docx        `word/document.xml` out of the zip: one line per `<w:p>`
    .pdf         the page content streams' text-showing operators

The PDF reader handles the PDFs a JD actually arrives as — exported from Word, Pages,
Google Docs, a print-to-PDF — and cannot handle a **scan**, which carries no text at
all. That is not a silent half-import: a PDF with no extractable text raises, and the
message says to paste the text instead.

Storage is `praxis/storage.py`'s, exactly like subjects and progress:

    <root>/jd/<id>.json     the canonical document — metadata and the normalized text

One file, because the text *is* the document; splitting it from its metadata would only
create two ways for an import to be half-there. The id is the title's slug plus a short
digest of the text, so re-importing the same posting rewrites one document instead of
piling up copies, and an edited posting is a new one.

CLI:
    python -m praxis.jd path/to/posting.pdf     import it, print the document
    python -m praxis.jd --list                  what has been imported
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import slugify  # noqa: E402
from praxis import storage  # noqa: E402

JD_VERSION = 1
JD_SUFFIX = ".json"

DEFAULT_TITLE = "job description"
TITLE_MAX = 120

#: The formats a posting arrives as, and what each one is called in the document.
KINDS = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": "pdf",
    ".docx": "docx",
}

MIMES = {
    "text": "text/plain",
    "markdown": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

SOURCES = ("paste", "upload")

#: A posting is a few pages of prose. Anything past this is a mis-picked file, and
#: refusing it before decoding is what keeps a 200MB video out of the storage root.
MAX_BYTES = 8 * 1024 * 1024

#: Below this there is nothing for the later bands to extract — an empty paste, or a
#: PDF that turned out to be a scan.
MIN_TEXT_CHARS = 40


class JDError(RuntimeError):
    """A job description could not be read. The message says what to do instead."""


# --- where a document lives -------------------------------------------------


def jd_dir() -> Path:
    """Where imported job descriptions are kept — the active storage backend decides.

    Beside the learner's subjects and progress under `praxis.storage`'s root, so a JD
    follows the app/drive/cloud choice like everything else the user owns.
    """
    return storage.jd_dir()


def jd_path(jd_id: str) -> Path:
    return jd_dir() / f"{jd_id}{JD_SUFFIX}"


def save_jd(doc: dict) -> Path:
    """Write the canonical document. Only ever called with one that parsed."""
    path = jd_path(doc["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def load_jd(jd_id: str) -> dict | None:
    """The stored document, or None when there isn't one (or it isn't readable JSON)."""
    try:
        data = json.loads(jd_path(jd_id).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_jds() -> list[dict]:
    """Every imported document as a summary — no `text`, newest first.

    The text of a dozen postings is not what a list view needs, and keeping it out of
    the list is what lets the UI show one without reading megabytes it will not render.
    """
    summaries = []
    directory = jd_dir()
    if not directory.is_dir():
        return summaries
    for path in directory.glob(f"*{JD_SUFFIX}"):
        doc = load_jd(path.name[: -len(JD_SUFFIX)])
        if doc and doc.get("id"):
            summaries.append({k: v for k, v in doc.items() if k != "text"})
    summaries.sort(key=lambda d: (str(d.get("created") or ""), str(d.get("id"))), reverse=True)
    return summaries


def delete_jd(jd_id: str) -> bool:
    """Remove one document. True if there was one to remove."""
    try:
        jd_path(jd_id).unlink()
    except OSError:
        return False
    return True


# --- normalizing ------------------------------------------------------------

#: Whitespace a posting picks up from a web page or a word processor and means as a
#: plain space. Zero-width characters are dropped outright — they are invisible here.
_SPACEY = "               　\t"
_ZERO_WIDTH = "​‌‍⁠﻿"

_BLANK_RUN = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """One canonical plain text out of whatever the reader produced.

    The later bands diff and quote this string, so two imports of the same posting — one
    pasted from a browser, one out of a PDF — have to agree. Line endings, Unicode form,
    the several kinds of space a word processor emits, and the run of blank lines a page
    break leaves behind are all normalized away; the words and the line structure are
    not touched.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = text.translate({ord(c): " " for c in _SPACEY})
    text = text.translate({ord(c): None for c in _ZERO_WIDTH})
    # Everything else non-printable is a parser artefact, not content.
    text = "".join(c for c in text if c == "\n" or unicodedata.category(c)[0] != "C")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip()


_MD_MARKS = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+|>\s+)|(\*\*|__|\*|_|`)")


def title_for(text: str, filename: str = "") -> str:
    """A display title: the posting's first line, else the file's name.

    A JD's first non-empty line is its job title far more often than not. A first line
    that is really a paragraph is not a title, so the filename wins there. Markdown
    marks are stripped from the title only — the text itself keeps them, because a
    posting pasted as markdown *is* plain text and the later bands read it as written.
    """
    first = next((line.strip() for line in text.split("\n") if line.strip()), "")
    first = _MD_MARKS.sub("", first).strip() if first else ""
    if first and len(first) <= TITLE_MAX:
        return first
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    if stem:
        return stem[:TITLE_MAX]
    return first[:TITLE_MAX] or DEFAULT_TITLE


def jd_id(title: str, text: str) -> str:
    """`<title-slug>-<digest>` — stable for the same posting, distinct for an edited one.

    The digest is what makes re-importing idempotent: the same bytes land on the same
    document rather than a second copy, which matters because a user who is not sure the
    upload worked will simply do it again.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(title, fallback='job-description')}-{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _document(text: str, *, source: str, kind: str, filename: str) -> dict:
    """The canonical shape. Every later band reads `text`; the rest is provenance."""
    text = normalize_text(text)
    if len(text) < MIN_TEXT_CHARS:
        where = filename or "what you pasted"
        raise JDError(
            f"no job description found in {where} — {len(text)} characters of text, and "
            f"a posting needs at least {MIN_TEXT_CHARS}. If this is a scanned or "
            "image-only document, paste the text instead."
        )
    title = title_for(text, filename)
    return {
        "version": JD_VERSION,
        "id": jd_id(title, text),
        "title": title,
        "source": source,
        "kind": kind,
        "mime": MIMES.get(kind, "text/plain"),
        "filename": filename,
        "text": text,
        "chars": len(text),
        "words": len(text.split()),
        "created": _now(),
    }


# --- reading each format ----------------------------------------------------


def kind_for(filename: str) -> str:
    """The document kind for a filename, or `JDError` naming what is supported."""
    suffix = Path(filename or "").suffix.lower()
    kind = KINDS.get(suffix)
    if kind:
        return kind
    supported = ", ".join(sorted(KINDS))
    got = suffix or "no extension"
    raise JDError(
        f"cannot read {filename or 'that file'} ({got}) — supported formats are "
        f"{supported}. Copy the posting's text and paste it instead."
    )


def _looks_binary(data: bytes) -> bool:
    """True for bytes no text decoder should be asked to guess at.

    CP1252 decodes *any* byte, so "undecodable" has to be decided before the fallback
    rather than by it — otherwise a JPEG becomes a page of mojibake and gets stored.
    """
    if b"\x00" in data[:4096]:
        return True
    sample = data[:4096]
    if not sample:
        return False
    control = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return control / len(sample) > 0.02


def decode_text(data: bytes, filename: str = "") -> str:
    """Bytes to text: a BOM if there is one, then UTF-8, then CP1252 for a Windows export.

    The BOM is read *before* the binary check on purpose — UTF-16 text is half NUL bytes,
    so the heuristic that keeps a JPEG out would throw out a perfectly good export from
    Notepad.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if _looks_binary(data):
        raise JDError(
            f"{filename or 'that file'} is not a text document — it looks like binary "
            "data. Save the posting as .txt, .md, .pdf or .docx, or paste its text."
        )
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise JDError(
        f"could not decode {filename or 'that file'} as text. Save it as UTF-8, or "
        "paste the posting's text."
    )


def docx_text(data: bytes, filename: str = "") -> str:
    """The visible text of a .docx: one line per paragraph, tabs and breaks kept.

    A .docx is a zip of XML, so this is `zipfile` plus `ElementTree` — imported here
    rather than at module scope, because a user who only ever pastes should not pay for
    a parser they never reach.
    """
    import io
    import zipfile
    from xml.etree import ElementTree

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = archive.read("word/document.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise JDError(
            f"{filename or 'that file'} is not a readable .docx ({exc}). If it is an "
            "older .doc, re-save it as .docx or paste the posting's text."
        ) from exc
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise JDError(f"{filename or 'that .docx'} has unreadable content: {exc}") from exc

    lines = []
    for paragraph in root.iter(f"{W}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append(" ")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


# The content-stream operators that end a run of text. A positioning operator means the
# next string starts somewhere else on the page, which for a posting means a new line.
_PDF_BREAKS = {b"Td", b"TD", b"T*", b"Tm", b"TL", b"ET", b"BT", b"'", b'"'}
_PDF_ESCAPES = {b"n": "\n", b"r": "\n", b"t": " ", b"b": "", b"f": "\n",
                b"(": "(", b")": ")", b"\\": "\\"}


def _pdf_literal(content: bytes, i: int) -> tuple[str, int]:
    """Read a `(…)` string starting just past the paren. Returns the text and the index."""
    out, depth, n = [], 1, len(content)
    while i < n:
        c = content[i : i + 1]
        if c == b"\\":
            nxt = content[i + 1 : i + 2]
            if nxt in _PDF_ESCAPES:
                out.append(_PDF_ESCAPES[nxt])
                i += 2
            elif nxt.isdigit():
                octal = b""
                i += 1
                while len(octal) < 3 and content[i : i + 1].isdigit():
                    octal += content[i : i + 1]
                    i += 1
                out.append(bytes([int(octal, 8) & 0xFF]).decode("cp1252", "replace"))
            elif nxt in (b"\n", b"\r"):  # a line continuation inside the string
                i += 2
            else:
                out.append(nxt.decode("cp1252", "replace"))
                i += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return "".join(out), i + 1
        out.append(c.decode("cp1252", "replace"))
        i += 1
    return "".join(out), i


def _pdf_hex(raw: bytes) -> str:
    """A `<…>` string. UTF-16BE when it carries a BOM, single bytes otherwise."""
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
    if len(digits) % 2:
        digits += b"0"
    try:
        data = bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return ""
    if data[:2] == b"\xfe\xff":
        return data[2:].decode("utf-16-be", "replace")
    return data.decode("cp1252", "replace")


def _pdf_stream_text(content: bytes) -> str:
    """The text a page content stream draws, one line per positioned run."""
    lines: list[str] = []
    run: list[str] = []
    i, n = 0, len(content)

    def flush() -> None:
        if run:
            lines.append("".join(run))
            run.clear()

    while i < n:
        c = content[i : i + 1]
        if c == b"(":
            text, i = _pdf_literal(content, i + 1)
            run.append(text)
        elif c == b"<" and content[i + 1 : i + 2] != b"<":
            end = content.find(b">", i)
            if end < 0:
                break
            run.append(_pdf_hex(content[i + 1 : end]))
            i = end + 1
        elif c == b"%":
            end = content.find(b"\n", i)
            i = n if end < 0 else end + 1
        elif c.isalpha() or c in (b"'", b'"'):
            end = i
            while end < n and (content[end : end + 1].isalnum() or content[end : end + 1] in (b"*", b"'", b'"')):
                end += 1
            if content[i:end] in _PDF_BREAKS:
                flush()
            i = max(end, i + 1)
        else:
            i += 1
    flush()
    return "\n".join(lines)


def pdf_text(data: bytes, filename: str = "") -> str:
    """The text of a PDF's pages, by way of its content streams.

    Every stream in the file is inflated and kept only if it reads like page content —
    it draws text (`BT … Tj`). That is what separates the pages from the embedded font
    programs and colour profiles that sit in the same file and inflate just as happily,
    without this module having to walk the whole object graph to find `/Type /Page`.

    A scan has no such stream, so it produces no text; `_document` refuses the empty
    result rather than storing a JD with nothing in it.
    """
    import zlib

    if not data[:5] == b"%PDF-":
        raise JDError(
            f"{filename or 'that file'} is not a PDF (no %PDF- header). Paste the "
            "posting's text instead."
        )
    pages: list[str] = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        try:
            content = zlib.decompress(raw)
        except zlib.error:
            content = raw  # an uncompressed content stream, which is legal and common
        if b"BT" not in content or (b"Tj" not in content and b"TJ" not in content):
            continue
        text = _pdf_stream_text(content)
        if text.strip():
            pages.append(text)
    if not pages:
        raise JDError(
            f"no text could be extracted from {filename or 'that PDF'} — it is most "
            "likely a scan or an image export. Paste the posting's text instead."
        )
    return "\n".join(pages)


#: kind -> reader. `text`/`markdown` share the decoder; only the other two pull a parser.
_READERS = {
    "text": decode_text,
    "markdown": decode_text,
    "docx": docx_text,
    "pdf": pdf_text,
}


def extract_text(data: bytes, kind: str, filename: str = "") -> str:
    """The plain text of one uploaded file's bytes, before normalization."""
    reader = _READERS.get(kind)
    if reader is None:
        raise JDError(f"no reader for '{kind}' documents")
    if not data:
        raise JDError(f"{filename or 'that file'} is empty.")
    if len(data) > MAX_BYTES:
        raise JDError(
            f"{filename or 'that file'} is {len(data) // (1024 * 1024)}MB — a job "
            f"description should be under {MAX_BYTES // (1024 * 1024)}MB. Is it the "
            "right file?"
        )
    return reader(data, filename)


# --- importing --------------------------------------------------------------


def document_from_text(text: str, *, title: str = "", filename: str = "",
                       kind: str = "text", source: str = "paste") -> dict:
    """The canonical document for pasted text. Pure — writes nothing."""
    if source not in SOURCES:
        raise JDError(f"unknown source '{source}'")
    if not isinstance(text, str):
        raise JDError("a job description has to be text")
    doc = _document(text, source=source, kind=kind, filename=filename)
    if title.strip():
        doc["title"] = title.strip()[:TITLE_MAX]
        doc["id"] = jd_id(doc["title"], doc["text"])
    return doc


def document_from_upload(filename: str, data: bytes, *, title: str = "") -> dict:
    """The canonical document for an uploaded file. Pure — writes nothing."""
    kind = kind_for(filename)
    text = extract_text(data, kind, filename)
    return document_from_text(
        text, title=title, filename=Path(filename).name, kind=kind, source="upload"
    )


def ingest_text(text: str, *, title: str = "") -> dict:
    """Import pasted text: normalize, then persist under the active backend."""
    doc = document_from_text(text, title=title)
    save_jd(doc)
    return doc


def ingest_upload(filename: str, data: bytes, *, title: str = "") -> dict:
    """Import an uploaded file: parse, normalize, then persist."""
    doc = document_from_upload(filename, data, title=title)
    save_jd(doc)
    return doc


def ingest_file(path: str | Path, *, title: str = "") -> dict:
    """Import a file from disk — the CLI's path, and the same code the upload takes."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise JDError(f"cannot read {path}: {exc}") from exc
    return ingest_upload(path.name, data, title=title)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - a convenience CLI
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for summary in list_jds():
            print(f"{summary['id']}  {summary.get('words', 0):>5} words  {summary['title']}")
        return 0
    if not argv:
        print(__doc__.strip().splitlines()[-3])
        return 2
    try:
        if argv[0] == "-":
            doc = ingest_text(sys.stdin.read())
        else:
            doc = ingest_file(argv[0])
    except JDError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in doc.items() if k != "text"}, indent=2))
    print(f"\nstored at {jd_path(doc['id'])}\n")
    print(doc["text"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

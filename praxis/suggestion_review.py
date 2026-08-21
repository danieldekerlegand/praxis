"""Persistence for the small, editable review state around ``praxis.suggest``."""

from __future__ import annotations

import json
from pathlib import Path

from praxis import storage


def path_for(jd_id: str) -> Path:
    return storage.suggestions_dir() / f"{jd_id}.json"


def load(jd_id: str) -> dict | None:
    try:
        value = json.loads(path_for(jd_id).read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def save(jd_id: str, document: dict) -> dict:
    path = path_for(jd_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return document


def public(document: dict) -> dict:
    """Return review state without exposing internal extraction bookkeeping."""
    return {
        "jd": document.get("jd", ""),
        "title": document.get("title", ""),
        "count": len(document.get("suggestions", [])),
        "suggestions": document.get("suggestions", []),
        "dropped": document.get("dropped", []),
        "accepted": document.get("accepted", []),
    }

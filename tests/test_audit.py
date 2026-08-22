import json
import urllib.error

from praxis.audit import audit_notebooks


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status


def notebook(*, code="x = 1\nprint(x)"):
    prose = "\n\n".join(
        f"## {n}. {heading}\n\n" + ("Useful explanation. " * 90)
        for n, heading in enumerate(
            ("What & Why", "Mental Model", "Key Concepts", "Setup", "Worked Examples",
             "Gotchas", "When to Use", "Resources"), 1)
    )
    prose += "\n\n- https://docs.python.org/3/\n- https://jupyter.org/\n- https://nbformat.readthedocs.io/"
    return {
        "metadata": {"praxis": {"status": "complete", "runnable": True}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": prose},
            {"cell_type": "code", "metadata": {}, "source": code},
            {"cell_type": "code", "metadata": {}, "source": "answer = 42"},
        ],
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(root, name, nb):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nb))
    return path


def test_audit_reports_dead_url_and_non_compiling_cell_without_writing(tmp_path):
    path = write_notebook(tmp_path, "broken.ipynb", notebook(code="if :"))
    before = path.read_bytes()

    def opener(request, timeout):
        if request.full_url.endswith("python.org/3/"):
            return Response(404)
        return Response(200)

    report = audit_notebooks(tmp_path, opener=opener)
    item = report["reports"][0]
    assert report["rotted"] == 1
    assert any("python.org/3/" in finding and "dead" in finding for finding in item["findings"])
    assert any("code cell 1" in finding for finding in item["findings"])
    assert path.read_bytes() == before


def test_audit_passes_healthy_notebook(tmp_path):
    write_notebook(tmp_path, "healthy.ipynb", notebook())

    report = audit_notebooks(tmp_path, opener=lambda request, timeout: Response(200))
    assert report["rotted"] == 0
    assert report["reports"][0]["status"] == "healthy"
    assert all(url["status"] == "live" for url in report["reports"][0]["urls"])


def test_network_failure_is_unchecked_not_live(tmp_path):
    write_notebook(tmp_path, "offline.ipynb", notebook())

    def opener(request, timeout):
        raise urllib.error.URLError("offline")

    report = audit_notebooks(tmp_path, opener=opener)
    assert report["rotted"] == 0
    assert all(url["status"] == "unchecked" for url in report["reports"][0]["urls"])

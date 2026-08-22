import json

from praxis import construct
from praxis.refresh import FLAGGED_FOR_HUMAN, FORCE_REGENERATE, refresh_notebook

from test_audit import Response, notebook, write_notebook
from test_construct import FakeClient, good_cells, reply


def test_flagged_refresh_is_read_only_by_default(tmp_path):
    path = write_notebook(tmp_path, "rotted.ipynb", notebook())
    before = path.read_bytes()

    result = refresh_notebook(
        path, root=tmp_path,
        opener=lambda request, timeout: Response(404),
    )

    assert result.outcome == FLAGGED_FOR_HUMAN
    assert result.audit["status"] == "rotted"
    assert path.read_bytes() == before


def test_force_refresh_uses_constructor_and_failed_candidate_is_untouched(tmp_path, monkeypatch):
    path = write_notebook(tmp_path, "rotted.ipynb", notebook())
    before = path.read_bytes()
    monkeypatch.setattr(construct, "topic_path", lambda domain, topic: path)

    result = refresh_notebook(
        path, root=tmp_path, force=True,
        opener=lambda request, timeout: Response(404),
        client=FakeClient(reply(good_cells()[:-1] + [{"type": "markdown", "source": "## 8. Resources\n\nTODO"}])),
        attempts=1,
        checks=False,
    )

    assert result.outcome == FORCE_REGENERATE
    assert result.construction is not None
    assert result.construction.status == "failed"
    assert path.read_bytes() == before


def test_force_refresh_of_healthy_seed_never_constructs(tmp_path, monkeypatch):
    path = write_notebook(tmp_path, "healthy.ipynb", notebook())
    called = []
    monkeypatch.setattr("praxis.refresh.construct_path", lambda *args, **kwargs: called.append(args))

    result = refresh_notebook(
        path, root=tmp_path, force=True,
        opener=lambda request, timeout: Response(200),
    )

    assert result.audit["status"] == "healthy"
    assert result.construction is None
    assert called == []

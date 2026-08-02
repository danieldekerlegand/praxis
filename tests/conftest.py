"""Suite-wide guard rails.

The user's subjects and progress now live under `praxis.storage`'s root, which by
default is the real per-user app-data directory (`~/Library/Application Support/...` on
macOS). A test that forgot to relocate one of them would therefore write into the
developer's own storage — so every test gets its own app directory, whether it asked for
one or not. The finer-grained `PRAXIS_SUBJECTS_DIR` / `PRAXIS_PROGRESS_DIR` fixtures in
individual test modules still work; this just makes the default safe.
"""

import pytest


@pytest.fixture(autouse=True)
def app_dir(monkeypatch, tmp_path):
    """Point storage at a temp app directory — never the developer's real one."""
    root = tmp_path / "app-data"
    monkeypatch.setenv("PRAXIS_APP_DIR", str(root))
    monkeypatch.delenv("PRAXIS_DATA_DIR", raising=False)
    return root

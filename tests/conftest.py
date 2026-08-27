import pytest
from fastapi.testclient import TestClient

import app as app_module
import backup
import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient wired to a fresh, empty temp SQLite db - never touches the
    real trades.db, and never writes a backup to OneDrive.

    db.get_conn() reads db.DB_PATH at call time (not at import time), so
    patching it here is enough to redirect every query the app makes for the
    duration of this test, including the init_db() call that TestClient's
    context-manager form triggers via the app's startup event.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_trades.db")
    monkeypatch.setattr(backup, "run_backup", lambda: None)
    with TestClient(app_module.app) as c:
        yield c

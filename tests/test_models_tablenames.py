"""Every mapped model must resolve to a table that exists after a schema sync
(the port dropped Flask-SQLAlchemy's implicit table naming)."""
import os
import sqlite3

import pytest

import core.config as config


def _tables(path):
    conn = sqlite3.connect(path)
    names = {r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    return names


def test_every_model_table_exists(client):
    from core.db import Base
    names = _tables(config.DB_PATH)
    missing = [t for t in Base.metadata.tables if t.lower() not in names]
    assert not missing, missing


REAL = os.path.join(os.path.dirname(__file__), 'fixtures', 'real_ScenePlay.db')


@pytest.mark.skipif(not os.path.exists(REAL), reason='no real DB fixture (tests/fixtures/real_ScenePlay.db)')
def test_real_db_upgrades_in_place(tmp_path):
    import shutil
    import core.db_migrate as db_migrate
    path = str(tmp_path / 'real.db')
    shutil.copy(REAL, path)
    before = _tables(path)
    db_migrate.sync_schema(path)
    assert db_migrate.current(path) == db_migrate.head()
    assert before <= _tables(path)

"""Standalone Alembic driver + the boot-time schema sync (the order app.py
used: WAL tune -> raw CREATE IF NOT EXISTS -> model create_all -> upgrade).
A failed migration RAISES: refusing to start beats running on a half-upgraded
database."""
import os

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

import core.config as config

SCHEMA_FAIL_MSG = ('Database schema migration failed — ScenePlay will not start on an '
                   'inconsistent database. A pre-upgrade ScenePlay.db can be restored '
                   'from backups/ if needed.')


def _cfg(db_path):
    cfg = Config(os.path.join(config.MIGRATIONS_DIR, 'alembic.ini'))
    cfg.set_main_option('script_location', config.MIGRATIONS_DIR)
    cfg.set_main_option('sqlalchemy.url', 'sqlite:///' + str(db_path).replace('%', '%%'))
    return cfg


def upgrade(db_path=None, revision='head'):
    command.upgrade(_cfg(db_path or config.DB_PATH), revision)


def head():
    return ScriptDirectory.from_config(_cfg(':memory:')).get_current_head()


def current(db_path=None):
    import sqlite3
    try:
        conn = sqlite3.connect(db_path or config.DB_PATH)
        row = conn.execute('SELECT version_num FROM alembic_version').fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def sync_schema(db_path=None):
    """Bring `db_path` (default: the configured DB) to the current schema.

    Never leaves the process's engine rebound: syncing another file (a
    restored archive in a test, schema_dump.py) uses a throwaway engine, so
    the web app keeps talking to config.DB_PATH afterwards."""
    import sql
    import core.db as _db
    import models  # noqa: F401  registers every mapped table
    path = db_path or config.DB_PATH
    prev_sql_db = sql.database
    sql.database = path
    try:
        sql.sqlite_tune()          # WAL mode — readers never block
        sql.create_table()         # raw-SQL tables (CREATE IF NOT EXISTS)
        if path == config.DB_PATH:
            _db.db.create_all()    # model tables on the live engine
        else:
            eng = _db._make_engine(path)
            try:
                _db.Base.metadata.create_all(eng)
            finally:
                eng.dispose()
        try:
            upgrade(path)
        except Exception as _e:
            raise RuntimeError(SCHEMA_FAIL_MSG) from _e
    finally:
        sql.database = prev_sql_db


def seed():
    """Idempotent reference data: defaultData JSON seeds and the built-in DCC
    library. Never blocks boot."""
    from defaultData import defaultData
    defaultData()
    try:
        import ttrpg.dcc_library as dcc_library
        import models.ttrpg as _ttrpg_models
        from core.db import db as _db
        from sql import appsettingGet, appsettingSet
        from datetime import datetime
        _now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _n = dcc_library.seed_if_needed(_db, _ttrpg_models, _now, appsettingGet, appsettingSet)
        if _n:
            print(f'DCC library: seeded {_n} built-in entries')
    except Exception as _e:   # never block boot on reference data
        print(f'DCC library seed skipped: {_e}')

"""Shared fixtures: a scratch sqlite file + the FastAPI app through TestClient
(lifespan running, so the SSE hub is live), JWT helpers for a DM and a
player. Env vars are set BEFORE config is imported. Workers, integrations and
crontab writes are always off under test."""
import os
import sys
import tempfile
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_tmp = tempfile.mkdtemp(prefix='sceneplay-test-')


def _cleanup_tmp():
    # every run used to leave its scratch tree behind (hundreds of MB of
    # backups/uploads per run filled /tmp); keep it only on request
    if os.environ.get('SP_TEST_KEEP_TMP'):
        print(f'[conftest] keeping {_tmp}')
        return
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)


import atexit  # noqa: E402
atexit.register(_cleanup_tmp)
os.environ.setdefault('SP_DB_PATH', os.path.join(_tmp, 'ScenePlay.db'))
os.environ.setdefault('SP_INSTANCE_DIR', os.path.join(_tmp, 'instance'))
os.environ.setdefault('SP_BACKUP_DIR', os.path.join(_tmp, 'backups'))
os.environ['SP_WORKERS'] = '0'
os.environ['SP_INTEGRATIONS'] = '0'
os.environ['SP_CRON_APPLY'] = '0'

# Stub the Linux audio lib BEFORE extensions is imported (it imports pulsectl
# at module level on posix). Harmless if the real one is installed.
for _mod in ('pulsectl',):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = types.ModuleType(_mod)

import pytest                              # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import core.config as config                              # noqa: E402
import core.db as _dbmod                        # noqa: E402
import core.db_migrate as db_migrate                          # noqa: E402
from core.db import db                          # noqa: E402
import models                              # noqa: E402,F401


def _fresh_schema(path):
    """Full boot-equivalent schema on `path` (raw tables + models + alembic)."""
    _dbmod.bind_path(path)
    db_migrate.sync_schema(path)
    db_migrate.seed()
    import core.boot as boot
    boot.seed_appsettings()


@pytest.fixture(scope='session')
def client():
    _fresh_schema(config.DB_PATH)
    from app import create_app
    app = create_app(testing=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def app():
    """Minimal DB-only fixture (the old Flask `app` fixture): in-memory-ish
    scratch database with every model table, rolled back/dropped after."""
    path = os.path.join(_tmp, f'unit-{os.getpid()}-{id(object())}.db')
    prev = config.DB_PATH
    _dbmod.bind_path(path)
    db.create_all()             # model tables at the current schema
    import sql
    sql.create_table()          # then the raw-only tables (tblAppSettings ...); IF NOT EXISTS skips the rest
    try:
        yield _dbmod
    finally:
        db.session.rollback()
        db.session.remove()
        db.drop_all()
        _dbmod.engine.dispose()
        _dbmod.bind_path(prev)          # the session-scoped client keeps its database
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture()
def fresh_db(tmp_path):
    path = str(tmp_path / 'ScenePlay.db')
    prev = config.DB_PATH
    _fresh_schema(path)
    yield path
    db.session.remove()
    _dbmod.bind_path(prev)


def _make_user(username, role, password='pw'):
    from models.user import tblUsers
    u = tblUsers.query.filter_by(username=username).first()
    if u is None:
        u = tblUsers(username=username, display_name=username.title(), role=role,
                     active=1, created_at='2026-01-01 00:00:00')
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
    return u


@pytest.fixture()
def dm(client):
    return _make_user('testdm', 'dm')


@pytest.fixture()
def player(client):
    return _make_user('testplayer', 'player')


@pytest.fixture()
def dm_token(dm):
    from security.jwt import issue_token
    return issue_token(dm)


@pytest.fixture()
def player_token(player):
    from security.jwt import issue_token
    return issue_token(player)


def auth(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture()
def character(app):
    """A minimal active character with known HP bounds."""
    from models.user import tblUsers
    from models.ttrpg import tblCharacters
    user = tblUsers(username='tester', display_name='Tester',
                    password_hash='x', role='player', active=1,
                    created_at='2026-01-01 00:00:00')
    db.session.add(user)
    db.session.flush()
    char = tblCharacters(
        user_id=user.user_id, name='Hero', char_class='Fighter', race='Human',
        level=3, hp_current=20, hp_max=30, ac=15, speed=30,
        active=1, created_at='2026-01-01 00:00:00',
    )
    db.session.add(char)
    db.session.commit()
    return char


# ── Flask-style client shim for verbatim-ported route tests ───────────────────
# The old tests did `a.test_client(user=dm).post(...).get_json()`; LegacyApp
# gives them the same surface over the session TestClient with a bearer token.

class _LegacyResp:
    def __init__(self, res):
        self._res = res
        self.status_code = res.status_code
        self.headers = res.headers

    def get_json(self):
        try:
            return self._res.json()
        except ValueError:
            return None

    def get_data(self, as_text=False):
        return self._res.text if as_text else self._res.content

    @property
    def text(self):
        return self._res.text


class LegacyClient:
    def __init__(self, client, user=None):
        self._c = client
        self._h = {}
        if user is not None:
            from security.jwt import issue_token
            self._h = auth(issue_token(user))

    def _call(self, method, path, json=None, data=None, headers=None, **kw):
        h = dict(self._h)
        h.update(headers or {})
        res = self._c.request(method, path, json=json, data=data, headers=h, **kw)
        # The request ran in its own session scope; drop the test thread's
        # identity map so the old "read it back with db.session.get" idiom
        # sees what the route committed (Flask tests shared one session).
        db.session.expire_all()
        return _LegacyResp(res)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path, **kw):
        return self._call('GET', path, **kw)

    def post(self, path, **kw):
        return self._call('POST', path, **kw)

    def delete(self, path, **kw):
        return self._call('DELETE', path, **kw)


class LegacyApp:
    """Stand-in for the per-test Flask app the old fixtures built: the session
    TestClient bound (via the `app` fixture) to a scratch database."""
    def __init__(self, client):
        self._client = client

    def test_client(self, user=None):
        return LegacyClient(self._client, user)


@pytest.fixture()
def legacy_app(app, client):
    return LegacyApp(client)


def fake_module(monkeypatch, dotted, obj):
    """Stand a fake in for a package module for one test: `import pkg.mod as x`
    inside the code under test resolves through BOTH sys.modules and the
    parent package attribute, so patch both."""
    import importlib
    import sys
    pkg, _, name = dotted.rpartition('.')
    monkeypatch.setitem(sys.modules, dotted, obj)
    if pkg:
        monkeypatch.setattr(importlib.import_module(pkg), name, obj, raising=False)
    return obj

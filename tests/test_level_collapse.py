"""Dungeon Crawler Carl level collapse: the DM's countdown + note live in the
session's DCC settings and reach every map viewer — the local map's state
poll, the OBS map source, and (via broadcast_game) the portal."""
import json

import pytest

from core.db import db

pytest.importorskip('routers.battlemap', reason='battlemap router lands in P4')


@pytest.fixture()
def bm_app(legacy_app, monkeypatch):
    from models.user import tblUsers
    from models.ttrpg import tblSessions, tblBattleMaps
    import routers.battlemap as bm_mod
    monkeypatch.setattr(bm_mod, '_push_map_state', lambda bm: None)
    dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm',
                  active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm); db.session.flush()
    sess = tblSessions(title='Crawl', status='active', created_at='2026-01-01 00:00:00',
                       game_system='dcc',
                       system_settings=json.dumps({'floor': 4, 'collapse_at': 1800000000,
                                                   'collapse_note': 'Stairs: NE'}))
    db.session.add(sess); db.session.flush()
    bm = tblBattleMaps(session_id=sess.session_id, name='Floor 4', grid_cols=10, grid_rows=10,
                       created_at='2026-01-01 00:00:00')
    db.session.add(bm); db.session.commit()
    return legacy_app, dm, sess.session_id, bm.map_id


def test_map_state_carries_collapse(bm_app):
    a, dm, sid, mid = bm_app
    d = a.test_client(user=dm).get(f'/ttrpg/battlemap/{mid}/state').get_json()
    assert d['collapse'] == {'floor': 4, 'at': 1800000000, 'note': 'Stairs: NE'}


def test_map_state_collapse_is_null_under_5e(bm_app):
    from models.ttrpg import tblSessions
    a, dm, sid, mid = bm_app
    s = db.session.get(tblSessions, sid); s.game_system = 'dnd5e'; s.system_settings = '{}'
    db.session.commit()
    d = a.test_client(user=dm).get(f'/ttrpg/battlemap/{mid}/state').get_json()
    assert d['collapse'] is None

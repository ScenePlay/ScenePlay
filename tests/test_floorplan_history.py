"""Floorplan history: every save snapshots the outgoing plan, pruned to the
last N; restore replays a snapshot through the normal validate/save path.
Also covers the dry_run preview mode (validate + normalize, no write)."""
import json

import pytest

from core.db import db



def _plan(wall_x=3):
    return {'format': 'sceneplay-floorplan', 'schema_version': 2,
            'grid': {'cols': 20, 'rows': 20},
            'walls': [{'x1': wall_x, 'y1': 0, 'x2': wall_x, 'y2': 6}],
            'doors': [], 'elevations': []}


@pytest.fixture()
def bm_client(legacy_app, monkeypatch):
    from models.user import tblUsers
    from models.ttrpg import tblSessions, tblBattleMaps
    import routers.battlemap as bm_mod
    monkeypatch.setattr(bm_mod, '_push_map_state', lambda bm: None)   # keep the relay out of it
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm)
    db.session.flush()
    sess = tblSessions(title='Night', status='planning', created_at='2026-01-01 00:00:00')
    db.session.add(sess)
    db.session.flush()
    bm = tblBattleMaps(session_id=sess.session_id, name='Crypt', grid_cols=20, grid_rows=20,
                       created_at='2026-01-01 00:00:00')
    db.session.add(bm)
    db.session.commit()
    return legacy_app.test_client(user=dm), bm.map_id, legacy_app


def _save(c, map_id, plan, dry_run=False):
    body = {'floorplan': plan}
    if dry_run:
        body['dry_run'] = True
    return c.post(f'/ttrpg/battlemap/{map_id}/floorplan', json=body).get_json()


class TestHistory:
    def test_save_snapshots_previous_plan(self, bm_client):
        c, map_id, _ = bm_client
        assert _save(c, map_id, _plan(3))['version'] == 1
        assert _save(c, map_id, _plan(7))['version'] == 2
        d = c.get(f'/ttrpg/battlemap/{map_id}/floorplan/history').get_json()
        assert d['ok'] and len(d['history']) == 1
        assert d['history'][0]['version'] == 1
        assert '1 walls' in d['history'][0]['summary']

    def test_save_returns_normalized_plan(self, bm_client):
        # The editor autosaves and adopts this instead of re-fetching (a
        # re-fetch would drop its selection and undo history).
        c, map_id, _ = bm_client
        plan = _plan(3)
        plan['props'] = [{'type': 'gravestone', 'x': 4, 'y': 4, 'scale': 9}]
        d = _save(c, map_id, plan)
        assert d['ok'] and d['version'] == 1
        fp = d['floorplan']
        assert fp['walls'][0]['x1'] == 3.0
        assert fp['props'][0]['scale'] == 4.0          # clamped, like the DB copy
        stored = c.get(f'/ttrpg/battlemap/{map_id}/floorplan').get_json()
        assert stored['floorplan'] == fp

    def test_restore_replays_snapshot_and_is_undoable(self, bm_client):
        c, map_id, _ = bm_client
        _save(c, map_id, _plan(3))
        _save(c, map_id, _plan(7))
        d = c.get(f'/ttrpg/battlemap/{map_id}/floorplan/history').get_json()
        hist_id = d['history'][0]['hist_id']
        r = c.post(f'/ttrpg/battlemap/{map_id}/floorplan/restore',
                   json={'hist_id': hist_id}).get_json()
        assert r['ok'] and r['version'] == 3
        # the restored geometry is the v1 wall...
        cur = c.get(f'/ttrpg/battlemap/{map_id}/floorplan').get_json()
        assert cur['floorplan']['walls'][0]['x1'] == 3.0
        # ...and the replaced v2 plan itself landed in history (undoable)
        d2 = c.get(f'/ttrpg/battlemap/{map_id}/floorplan/history').get_json()
        assert any(h['version'] == 2 for h in d2['history'])

    def test_history_pruned_to_cap(self, bm_client):
        import routers.battlemap as bm_mod
        c, map_id, _ = bm_client
        for i in range(bm_mod.FLOORPLAN_HISTORY_KEEP + 4):
            _save(c, map_id, _plan(1 + i * 0.2))
        d = c.get(f'/ttrpg/battlemap/{map_id}/floorplan/history').get_json()
        assert len(d['history']) == bm_mod.FLOORPLAN_HISTORY_KEEP

    def test_restore_unknown_id_404(self, bm_client):
        c, map_id, _ = bm_client
        r = c.post(f'/ttrpg/battlemap/{map_id}/floorplan/restore',
                   json={'hist_id': 999})
        assert r.status_code == 404


class TestDryRun:
    def test_dry_run_validates_without_writing(self, bm_client):
        from models.ttrpg import tblBattleMapFloorplans
        c, map_id, a = bm_client
        d = _save(c, map_id, _plan(3), dry_run=True)
        assert d['ok'] and d['dry_run']
        assert d['floorplan']['walls'][0]['x1'] == 3.0
        assert '1 walls' in d['summary']
        assert tblBattleMapFloorplans.query.filter_by(map_id=map_id).first() is None

    def test_dry_run_reports_unknown_textures(self, bm_client):
        c, map_id, _ = bm_client
        plan = _plan(3)
        plan['walls'][0]['texture'] = 'no_such_texture'
        plan['zones'] = [{'rects': [{'x1': 0, 'y1': 0, 'x2': 5, 'y2': 5}],
                          'floor_texture': 'flagstone'}]
        d = _save(c, map_id, plan, dry_run=True)
        assert d['ok']
        assert d['unknown_textures'] == ['no_such_texture']   # flagstone is builtin

    def test_dry_run_rejects_bad_plan(self, bm_client):
        c, map_id, _ = bm_client
        r = c.post(f'/ttrpg/battlemap/{map_id}/floorplan',
                   json={'floorplan': {'schema_version': 9}, 'dry_run': True})
        assert r.status_code == 400

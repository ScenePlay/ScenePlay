"""Remote producer console, local half (integrations/relay_producer): the
users push carries roles, execute() dispatches / rejects / expires / dedups,
presence counts as consoles, pushes only flow to a connected socket, and
relay_ws routes the new frames. OBS is stubbed as in test_producer_api."""
import base64
import json

import pytest

import integrations.relay_producer as rp
import integrations.relay_ws as rw
from core.db import db


@pytest.fixture()
def obs(monkeypatch):
    import integrations.obs_ws as obs_ws
    calls = []
    state = obs_ws._blank_cache()
    state.update({'scenes': ['ScenePlay Party', 'ScenePlay Map'],
                  'current_scene': 'ScenePlay Party', 'preview_scene': 'ScenePlay Map',
                  'transitions': [{'name': 'Cut', 'fixed': True}],
                  'current_transition': 'Cut', 'transition_ms': 300})
    flags = {'connected': True}

    def rec(name, ret=None):
        def f(*a, **k):
            calls.append((name,) + a)
            return ret
        return f

    monkeypatch.setattr(obs_ws, 'connected', lambda: flags['connected'])
    monkeypatch.setattr(obs_ws, 'current_state', lambda: dict(state))
    monkeypatch.setattr(obs_ws, 'set_studio_mode', rec('studio'))
    monkeypatch.setattr(obs_ws, 'set_meter_events', rec('meters'))
    monkeypatch.setattr(obs_ws, 'set_preview_scene',
                        lambda name, timeout=3: (calls.append(('preview', name)), state.__setitem__('preview_scene', name)))
    monkeypatch.setattr(obs_ws, 'preview_scene', lambda: state['preview_scene'])
    monkeypatch.setattr(obs_ws, 'set_transition', rec('transition'))
    monkeypatch.setattr(obs_ws, 'trigger_transition', rec('take'))
    monkeypatch.setattr(obs_ws, 'record_chapter', rec('chapter'))
    monkeypatch.setattr(obs_ws, 'screenshot', rec('shot', b'\xff\xd8jpeg'))
    monkeypatch.setattr(obs_ws, 'levels', lambda: ({'ScenePlay Music': [0.5]}, 1.0))
    return {'calls': calls, 'state': state, 'flags': flags}


@pytest.fixture()
def fresh(monkeypatch, legacy_app):
    import routers.producer as p
    monkeypatch.setattr(p, '_consoles', {})
    monkeypatch.setattr(p, '_off_timer', None)
    monkeypatch.setattr(p, '_sweep_timer', None)
    monkeypatch.setattr(p, '_armed', {'key': None})
    monkeypatch.setattr(p, '_remote', {'consoles': 0})
    monkeypatch.setattr(p, '_shots_cache', {'at': 0.0, 'key': None, 'value': []})
    monkeypatch.setattr(p, '_schedule_off', lambda: None)
    monkeypatch.setattr(rp, '_app', None)
    from sql import appsettingSet
    appsettingSet(rp.LEDGER_KEY, '[]')
    appsettingSet(rp.LEDGER_SESSION_KEY, '')
    yield p


class FakeWs:
    def __init__(self):
        self.sent = []

    def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.fixture()
def socket(monkeypatch):
    ws = FakeWs()
    monkeypatch.setattr(rw, '_ws', ws)
    monkeypatch.setattr(rw, '_state', 'connected')
    return ws


# ── users push ───────────────────────────────────────────────────────────────

def test_push_session_users_carries_role(legacy_app, monkeypatch):
    import integrations.relay_broadcaster as rb
    from models.user import tblUsers
    db.session.add(tblUsers(username='gm1', display_name='GM', password_hash='h', role='dm',
                            active=1, created_at='2026-01-01 00:00:00'))
    db.session.add(tblUsers(username='pl1', display_name='P', password_hash='h', role='player',
                            active=1, created_at='2026-01-01 00:00:00'))
    db.session.commit()
    monkeypatch.setattr(rb, '_active', lambda: {'session_id': 's1'})
    captured = {}
    monkeypatch.setattr(rb, '_enqueue', lambda key, fn: captured.setdefault('fn', fn))
    monkeypatch.setattr(rb, '_exec_cfg', lambda: {'session_id': 's1'})
    monkeypatch.setattr(rb, '_post', lambda path, payload, c: captured.setdefault('payload', payload))
    rb.push_session_users()
    captured['fn']()
    roles = {u['username']: u['role'] for u in captured['payload']['users']}
    assert roles['gm1'] == 'dm' and roles['pl1'] == 'player'


# ── execute ──────────────────────────────────────────────────────────────────

def test_execute_arm_applies_and_dedups(fresh, obs):
    row = {'id': 7, 'session_id': 's1', 'cmd': 'arm', 'args': json.dumps({'key': 'map'}), 'age_s': 0}
    assert rp.execute(row) == (7, 'applied', '')
    assert ('preview', 'ScenePlay Map') in obs['calls']
    obs['calls'].clear()
    assert rp.execute(row) == (7, 'applied', '')       # replayed: re-acked, not re-run
    assert obs['calls'] == []


def test_execute_expired_never_runs(fresh, obs):
    row = {'id': 8, 'session_id': 's1', 'cmd': 'take', 'args': {}, 'age_s': 12}
    cid, status, err = rp.execute(row)
    assert (cid, status) == (8, 'expired')
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_execute_take_honours_explicit_ttl(fresh, obs):
    row = {'id': 9, 'session_id': 's1', 'cmd': 'take', 'args': {}, 'age_s': 12, 'ttl_s': 20}
    assert rp.execute(row)[1] == 'applied'
    assert any(c[0] == 'take' for c in obs['calls'])


def test_execute_rejects_unknown_and_obs_down(fresh, obs):
    assert rp.execute({'id': 10, 'session_id': 's1', 'cmd': 'nope', 'args': {}})[1] == 'rejected'
    obs['flags']['connected'] = False
    cid, status, err = rp.execute({'id': 11, 'session_id': 's1', 'cmd': 'arm', 'args': {'key': 'map'}})
    assert status == 'rejected' and 'OBS' in err


def test_execute_settings_commands_work_without_obs(fresh, obs):
    obs['flags']['connected'] = False
    from sql import appsettingGet
    assert rp.execute({'id': 12, 'session_id': 's1', 'cmd': 'countdown', 'args': {'seconds': 90}})[1] == 'applied'
    assert appsettingGet('producer_countdown_until', '')
    assert rp.execute({'id': 13, 'session_id': 's1', 'cmd': 'marker', 'args': {'note': 'boss'}})[1] == 'applied'
    assert 'boss' in appsettingGet('producer_markers', '')
    assert rp.execute({'id': 14, 'session_id': 's1', 'cmd': 'auto_cam_pause', 'args': {'paused': True}})[1] == 'applied'
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '1'
    assert rp.execute({'id': 15, 'session_id': 's1', 'cmd': 'markers_clear', 'args': {}})[1] == 'applied'
    assert json.loads(appsettingGet('producer_markers', '[]') or '[]') == []


def test_ledger_resets_with_session(fresh, obs):
    rp.execute({'id': 1, 'session_id': 's1', 'cmd': 'marker', 'args': {'note': 'a'}})
    obs['calls'].clear()
    # a new relay session restarts ids at 1: the same id must run again
    assert rp.execute({'id': 1, 'session_id': 's2', 'cmd': 'arm', 'args': {'key': 'map'}})[1] == 'applied'
    assert ('preview', 'ScenePlay Map') in obs['calls']


def test_execute_sceneplay_commands(fresh, obs, monkeypatch):
    import routers.public as pub
    hits = []
    monkeypatch.setattr(pub, 'activatescene', lambda id=None: hits.append(('scene', id)) or {'ok': True})
    monkeypatch.setattr(pub, 'nextsong', lambda: hits.append(('skip',)))
    monkeypatch.setattr(pub, 'lights_off', lambda: hits.append(('lights',)))
    import extensions
    monkeypatch.setattr(extensions, 'setvolume', lambda v: hits.append(('vol', v)))
    for cmd, args in (('activate_scene', {'scene_id': 3}), ('skip', {}), ('lights_off', {}), ('set_volume', {'volume': 40})):
        assert rp.execute({'id': hash(cmd) % 10000 + 100, 'session_id': 's1', 'cmd': cmd, 'args': args})[1] == 'applied'
    assert hits == [('scene', '3'), ('skip',), ('lights',), ('vol', 40)]


def test_execute_kill_tears_down_lights_too(fresh, obs, monkeypatch):
    """Kill = queue kill THEN the pseudo-scene -1 teardown (lights off on
    RPiLED, WLED and the relay; CurrentScene cleared) — the same pair the
    1.x home Kill button, cron and the TTRPG pages send."""
    import routers.public as pub
    hits = []
    monkeypatch.setattr(pub, 'killqueue', lambda: hits.append(('kill',)))
    monkeypatch.setattr(pub, 'activatescene', lambda id=None: hits.append(('scene', id)) or {'ok': True})
    assert rp.execute({'id': 777, 'session_id': 's1', 'cmd': 'kill', 'args': {}})[1] == 'applied'
    assert hits == [('kill',), ('scene', '-1')]


# ── presence / consoles ──────────────────────────────────────────────────────

def test_presence_counts_as_console_and_enables_studio(fresh, obs):
    rp.set_presence(2)
    assert fresh.console_count() == 2
    assert any(c[0] == 'studio' and c[1] is True for c in obs['calls'])
    rp.link_down()
    assert fresh.console_count() == 0


def test_link_up_replays_presence_then_commands(fresh, obs, monkeypatch):
    seen = []
    monkeypatch.setattr(rp, 'enqueue', lambda row: seen.append(row['id']))
    rp.link_up({'producer_consoles': 1, 'pending_producer_commands': [{'id': 5, 'cmd': 'take'}]})
    assert fresh.remote_console_count() == 1 and seen == [5]


# ── push ─────────────────────────────────────────────────────────────────────

def test_push_state_and_frame_only_when_connected(fresh, obs, socket, monkeypatch):
    assert rp.push_state() is True
    frame = socket.sent[-1]
    assert frame['type'] == 'producer_state' and 'id' not in frame
    assert 'audio_rows' in frame['payload'] and 'levels' in frame['payload']
    assert frame['payload']['program'] == 'ScenePlay Party'

    assert rp.push_frame('program') is True
    f = socket.sent[-1]
    assert f['type'] == 'producer_frame' and f['payload']['target'] == 'program'
    assert base64.b64decode(f['payload']['jpeg_b64']) == b'\xff\xd8jpeg'

    monkeypatch.setattr(rw, '_state', 'reconnecting')
    assert rp.push_state() is False and rp.push_frame('program') is False


def test_event_listener_marks_dirty_only_with_remote_consoles(fresh, obs):
    rp._dirty.clear()
    rp._on_event('obs', {})
    assert not rp._dirty.is_set()
    rp.set_presence(1)
    rp._dirty.clear()
    rp._on_event('obs', {})
    assert rp._dirty.is_set()


# ── relay_ws routing ─────────────────────────────────────────────────────────

def test_relay_ws_routes_producer_frames(fresh, monkeypatch):
    calls = []
    monkeypatch.setattr(rp, 'enqueue', lambda row: calls.append(('cmd', row['id'])))
    monkeypatch.setattr(rp, 'set_presence', lambda n: calls.append(('presence', n)))
    import types
    fake_app = types.SimpleNamespace(app_context=lambda: __import__('contextlib').nullcontext())
    monkeypatch.setattr(rw, '_app', fake_app)
    cfg = {'url': 'http://relay', 'session_id': 's1', 'secret': 'x'}
    rw._handle_event({'type': 'producer_command', 'data': {'id': 3, 'cmd': 'take'}}, cfg)
    rw._handle_event({'type': 'producer_presence', 'data': {'consoles': 2}}, cfg)
    assert calls == [('cmd', 3), ('presence', 2)]


def test_ack_uses_socket_then_http_fallback(fresh, socket, monkeypatch):
    assert rp._ack(3, 'applied', '') is True
    assert socket.sent[-1] == {'type': 'producer_ack', 'payload': {'id': 3, 'status': 'applied', 'error': ''}}
    monkeypatch.setattr(rw, '_state', 'reconnecting')
    posted = {}
    import requests
    monkeypatch.setattr(requests, 'post', lambda url, **k: posted.update(url=url, json=k['json']))
    from sql import appsettingSet
    appsettingSet('relay_url', 'http://relay')
    appsettingSet('relay_secret', 'x')
    assert rp._ack(4, 'expired', 'late', session_id='s1') is True
    assert posted['url'].endswith('/api/v1/session/s1/producer/ack') and posted['json']['status'] == 'expired'


def test_execute_barge_and_profile(fresh, obs, monkeypatch):
    hits = []
    monkeypatch.setattr(fresh, 'set_barge', lambda on: hits.append(('barge', on)) or {'ok': True})
    monkeypatch.setattr(fresh, 'set_profile', lambda name, icon=None: hits.append(('name', name)) or {'ok': True})
    assert rp.execute({'id': 40, 'session_id': 's1', 'cmd': 'barge', 'args': {'on': False}})[1] == 'applied'
    assert rp.execute({'id': 41, 'session_id': 's1', 'cmd': 'producer_profile', 'args': {'name': 'Eric'}})[1] == 'applied'
    assert hits == [('barge', False), ('name', 'Eric')]


def test_execute_transition(fresh, obs):
    from sql import appsettingGet
    # the stub OBS knows only Cut (fixed): saved with no duration
    assert rp.execute({'id': 50, 'session_id': 's1', 'cmd': 'transition', 'args': {'name': 'Cut', 'ms': 500}})[1] == 'applied'
    assert appsettingGet('obs_transition', '') == 'Cut'      # the saved fade length is left alone
    assert rp.execute({'id': 51, 'session_id': 's1', 'cmd': 'transition', 'args': {'name': 'Nope', 'ms': 500}})[1] == 'rejected'

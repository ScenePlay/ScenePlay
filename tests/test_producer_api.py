"""Producer console API. obs_ws is stubbed at the function level (the same
idea as tests/test_obs_output.py); the settings table is the scratch DB's."""
import pytest

from core.db import db


@pytest.fixture()
def dm_client(legacy_app):
    from models.user import tblUsers
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm)
    db.session.commit()
    with legacy_app.test_client(user=dm) as c:
        yield c


@pytest.fixture()
def obs(monkeypatch):
    """Recording stub of every obs_ws call the producer router makes."""
    import integrations.obs_ws as obs_ws
    calls = []
    state = obs_ws._blank_cache()
    state.update({'scenes': ['ScenePlay Party', 'ScenePlay Map', 'Player - Carl', 'DM - Jankis'],
                  'current_scene': 'ScenePlay Party',
                  'transitions': [{'name': 'Cut', 'fixed': True}, {'name': 'Fade', 'fixed': False}],
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
def fresh(monkeypatch):
    """No consoles registered, no off-timer, no sweep-timer, nothing armed."""
    import routers.producer as p
    monkeypatch.setattr(p, '_consoles', {})
    monkeypatch.setattr(p, '_off_timer', None)
    monkeypatch.setattr(p, '_sweep_timer', None)
    monkeypatch.setattr(p, '_armed', {'key': None})
    yield p
    if p._off_timer is not None:          # a real Timer scheduled by a test: never let it fire later
        p._off_timer.cancel()
        p._off_timer = None
    if p._sweep_timer is not None:        # ditto for a real sweeper Timer
        p._sweep_timer.cancel()
        p._sweep_timer = None


def _party(monkeypatch, names=('Carl',)):
    """Stand in for the OBS router's party ordering: one on-stream player per
    name plus the DM tile, with the same scene naming the router uses."""
    import routers.obs as obs

    class C:
        def __init__(self, cid, name):
            self.character_id, self.name = cid, name

    chars = [C(i + 1, n) for i, n in enumerate(names)] + [C(obs.DM_TILE_ID, 'Jankis')]
    monkeypatch.setattr(obs, '_ordered_party', lambda include_offstage=False: chars)
    return chars


def test_open_turns_studio_mode_on_and_pauses_auto_cam(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/session')
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] and body['console_id'] and body['consoles'] == 1
    assert ('studio', True) in obs['calls'] and ('meters', True) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '1'
    assert fresh.producer_active() is True


def test_auto_cam_is_off_while_producer_pauses_it(dm_client, obs, fresh, monkeypatch):
    import routers.obs as ro
    from sql import appsettingSet
    appsettingSet('obs_auto_cam', '1')
    assert ro.auto_cam_on() is True
    appsettingSet(fresh.PAUSE_KEY, '1')
    assert ro.auto_cam_on() is False
    appsettingSet(fresh.PAUSE_KEY, '0')
    assert ro.auto_cam_on() is True


def test_pause_toggle(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': False})
    assert r.get_json() == {'ok': True, 'paused': False}
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': True})
    assert r.get_json()['paused'] is True and appsettingGet(fresh.PAUSE_KEY, '0') == '1'


def test_last_close_turns_studio_mode_off_after_grace(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn):
            timers.append((secs, fn)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    cid2 = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    dm_client.delete(f'/ttrpg/producer/api/session/{cid}')
    off_timers = [t for t in timers if t[0] == fresh.STUDIO_OFF_GRACE_S]
    assert off_timers == []                               # one console still open
    dm_client.delete(f'/ttrpg/producer/api/session/{cid2}')
    off_timers = [t for t in timers if t[0] == fresh.STUDIO_OFF_GRACE_S]
    assert len(off_timers) == 1
    obs['calls'].clear()
    off_timers[0][1]()                                    # grace elapsed
    assert ('studio', False) in obs['calls'] and ('meters', False) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'


def test_reopen_within_grace_cancels_the_off_timer(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    cancelled = []

    class FakeTimer:
        def __init__(self, secs, fn):
            self.secs = secs; self.daemon = False
        def start(self): pass
        def cancel(self): cancelled.append(self.secs)

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    dm_client.delete(f'/ttrpg/producer/api/session/{cid}')
    dm_client.post('/ttrpg/producer/api/session')
    assert [s for s in cancelled if s == fresh.STUDIO_OFF_GRACE_S] == [fresh.STUDIO_OFF_GRACE_S]


def test_sweeper_reaps_a_crashed_console(dm_client, obs, fresh, monkeypatch):
    """No pings, no DELETE, no other call: the sweeper alone must notice the
    dead console and schedule Studio Mode off."""
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn):
            timers.append((secs, fn)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    assert [t[0] for t in timers] == [fresh.SWEEP_S]           # sweeper armed on first open
    fresh._consoles[cid] -= fresh.PING_TTL_S + 1                # the tab died
    timers[0][1]()                                              # sweep fires
    secs = [t[0] for t in timers]
    assert fresh.STUDIO_OFF_GRACE_S in secs                     # off timer scheduled
    assert secs.count(fresh.SWEEP_S) == 1                       # sweeper did not re-arm: nobody left


def test_sweeper_rearms_while_a_console_is_alive(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn):
            timers.append((secs, fn)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    dm_client.post('/ttrpg/producer/api/session')
    timers[0][1]()
    assert [t[0] for t in timers] == [fresh.SWEEP_S, fresh.SWEEP_S]


def test_stale_console_is_reaped_after_ping_ttl(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    assert dm_client.post('/ttrpg/producer/api/session/ping', json={'console_id': cid}).get_json()['ok'] is True
    fresh._consoles[cid] -= fresh.PING_TTL_S + 1
    assert fresh.console_count() == 0
    assert dm_client.post('/ttrpg/producer/api/session/ping', json={'console_id': cid}).get_json()['ok'] is False


def test_state_document(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.get('/ttrpg/producer/api/state')
    d = r.get_json()
    assert d['connected'] is True and d['program'] == 'ScenePlay Party' and d['preview'] == ''
    keys = [s['key'] for s in d['shots']]
    assert keys == ['party', 'map', 'char:1', 'dm', 'pre', 'intermission', 'post']
    carl = next(s for s in d['shots'] if s['key'] == 'char:1')
    assert carl == {'key': 'char:1', 'label': 'Carl', 'scene': 'Player - Carl',
                    'kind': 'player', 'built': True, 'character_id': 1}
    pre = next(s for s in d['shots'] if s['key'] == 'pre')
    assert pre['built'] is False and pre['kind'] == 'special'
    assert d['transitions'] == ['Cut', 'Fade'] and d['transition'] == 'Cut' and d['transition_ms'] == 300
    assert d['consoles'] == 0 and d['armed'] is None and d['auto_cam_paused'] is False
    assert set(d) >= {'studio_mode', 'recording', 'streaming', 'record_timecode', 'stream_timecode',
                      'last_switch', 'countdown_until', 'clock_start', 'markers', 'session'}


def test_state_needs_dm(legacy_app, obs, fresh):
    from models.user import tblUsers
    pl = tblUsers(username='pl', display_name='P', password_hash='x', role='player', active=1,
                  created_at='2026-01-01 00:00:00')
    db.session.add(pl); db.session.commit()
    with legacy_app.test_client(user=pl) as c:
        assert c.get('/ttrpg/producer/api/state').status_code == 403

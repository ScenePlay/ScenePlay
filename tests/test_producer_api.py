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
        def __init__(self, secs, fn, args=()):
            timers.append((secs, fn, args)); self.daemon = False
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
    off_timers[0][1](*off_timers[0][2])                   # grace elapsed
    assert ('studio', False) in obs['calls'] and ('meters', False) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'


def test_reopen_within_grace_cancels_the_off_timer(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    cancelled = []

    class FakeTimer:
        def __init__(self, secs, fn, args=()):
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
        def __init__(self, secs, fn, args=()):
            timers.append((secs, fn, args)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    assert [t[0] for t in timers] == [fresh.SWEEP_S]           # sweeper armed on first open
    fresh._consoles[cid] -= fresh.PING_TTL_S + 1                # the tab died
    timers[0][1](*timers[0][2])                                 # sweep fires
    secs = [t[0] for t in timers]
    assert fresh.STUDIO_OFF_GRACE_S in secs                     # off timer scheduled
    assert secs.count(fresh.SWEEP_S) == 1                       # sweeper did not re-arm: nobody left


def test_sweeper_rearms_while_a_console_is_alive(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn, args=()):
            timers.append((secs, fn, args)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    dm_client.post('/ttrpg/producer/api/session')
    timers[0][1](*timers[0][2])
    assert [t[0] for t in timers] == [fresh.SWEEP_S, fresh.SWEEP_S]


def test_reopen_within_sweep_window_keeps_one_sweeper(dm_client, obs, fresh, monkeypatch):
    """Close then reopen before the sweeper fired: the old sweeper is cancelled
    and, even if it still fires, retires itself instead of re-arming."""
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn, args=()):
            self.secs, self.fn, self.args, self.cancelled = secs, fn, args, False
            self.daemon = False
            timers.append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    first_sweep = [t for t in timers if t.secs == fresh.SWEEP_S][0]
    dm_client.delete(f'/ttrpg/producer/api/session/{cid}')
    dm_client.post('/ttrpg/producer/api/session')
    sweeps = [t for t in timers if t.secs == fresh.SWEEP_S]
    assert len(sweeps) == 2 and first_sweep.cancelled
    first_sweep.fn(*first_sweep.args)                    # the old chain fires anyway
    assert len([t for t in timers if t.secs == fresh.SWEEP_S]) == 2   # it did not re-arm
    sweeps[1].fn(*sweeps[1].args)                        # the live chain fires
    assert len([t for t in timers if t.secs == fresh.SWEEP_S]) == 3   # and re-arms


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


def test_arm_sets_preview(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'char:1'})
    assert r.get_json() == {'ok': True, 'armed': 'char:1', 'scene': 'Player - Carl'}
    assert ('preview', 'Player - Carl') in obs['calls']
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] == 'char:1'


def test_arm_unknown_and_unbuilt(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    assert dm_client.post('/ttrpg/producer/api/arm', json={'key': 'nope'}).status_code == 400
    r = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'pre'})
    body = r.get_json()
    assert body['ok'] is False and 'Build' in body['error']
    assert not any(c[0] == 'preview' for c in obs['calls'])


def test_arm_when_disconnected(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    obs['flags']['connected'] = False
    body = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'}).get_json()
    assert body == {'ok': False, 'error': 'OBS is not connected.'}


def test_take_with_nothing_armed(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body == {'ok': False, 'error': 'Nothing armed.'}
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_take_uses_chosen_transition_and_tags_the_cut(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import routers.obs as ro
    emitted = []
    monkeypatch.setattr(ro, '_emit', lambda kind, **x: emitted.append((kind, x)))
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    r = dm_client.post('/ttrpg/producer/api/take', json={'transition': 'Cut'})
    assert r.get_json() == {'ok': True, 'scene': 'ScenePlay Map', 'transition': 'Cut'}
    assert ('transition', 'Cut', None) in obs['calls'] and ('take',) in obs['calls']
    assert ('cut', {'target': 'map', 'scene': 'ScenePlay Map', 'by': 'producer'}) in emitted
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] is None


def test_auto_is_a_fade_take(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'dm'})
    r = dm_client.post('/ttrpg/producer/api/auto', json={'ms': 500})
    assert r.get_json() == {'ok': True, 'scene': 'DM - Jankis', 'transition': 'Fade'}
    assert ('transition', 'Fade', 500) in obs['calls']


def test_take_obs_rejection_is_reported(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import integrations.obs_ws as obs_ws
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'party'})

    def boom(timeout=3):
        raise obs_ws.ObsRejected(500, 'studio mode is off')
    monkeypatch.setattr(obs_ws, 'trigger_transition', boom)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is False and 'studio mode is off' in body['error']


def test_transition_default(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/transition', json={'name': 'Fade', 'ms': 700})
    assert r.get_json() == {'ok': True, 'transition': 'Fade', 'ms': 700}
    assert ('transition', 'Fade', 700) in obs['calls']


def test_broadcast_cut_is_tagged(dm_client, obs, fresh, monkeypatch):
    """The OBS router's own cut tells switch_scene who did it."""
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    seen = []
    monkeypatch.setattr(obs_ws, 'switch_scene', lambda scene, **k: seen.append((scene, k.get('by'))))
    monkeypatch.setattr(obs_ws, 'scene_list', lambda refresh=False: (['ScenePlay Map'], 'ScenePlay Party'))
    monkeypatch.setattr(ro, 'map_scene_name', lambda: 'ScenePlay Map')
    monkeypatch.setattr(ro, '_special_scene', lambda special: '')
    r = dm_client.post('/ttrpg/obs/api/cut/map')
    assert r.status_code == 200 and seen == [('ScenePlay Map', 'broadcast')]


def test_second_take_without_rearming_is_refused(dm_client, obs, fresh, monkeypatch):
    """After a Take, Preview still names the scene that is now Program; the
    console must not fire a second, empty-target cut."""
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    assert dm_client.post('/ttrpg/producer/api/take', json={}).get_json()['ok'] is True
    obs['state']['current_scene'] = 'ScenePlay Map'          # what OBS reports after the cut
    obs['calls'].clear()
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body == {'ok': False, 'error': 'Nothing armed.'}
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_take_of_a_preview_armed_inside_obs(dm_client, obs, fresh, monkeypatch):
    """Preview moved from OBS's own UI (event, no console arm) and differs from
    Program: a Take is legitimate and reports the scene."""
    _party(monkeypatch)
    obs['state']['preview_scene'] = 'Player - Carl'
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is True and body['scene'] == 'Player - Carl'


def test_transition_when_disconnected(dm_client, obs, fresh, monkeypatch):
    obs['flags']['connected'] = False
    body = dm_client.post('/ttrpg/producer/api/transition', json={'name': 'Fade', 'ms': 300}).get_json()
    assert body == {'ok': False, 'error': 'OBS is not connected.'}
    assert not any(c[0] == 'transition' for c in obs['calls'])


def test_countdown_seconds_until_and_clear(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'seconds': 600})
    body = r.get_json()
    assert body['ok'] and len(body['until']) == 19
    assert appsettingGet('producer_countdown_until', '') == body['until']
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'until': '2030-01-01 20:15:00'})
    assert r.get_json()['until'] == '2030-01-01 20:15:00'
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'clear': True})
    assert r.get_json() == {'ok': True, 'until': ''}
    assert appsettingGet('producer_countdown_until', '') == ''


def test_countdown_rejects_garbage(dm_client, obs, fresh):
    assert dm_client.post('/ttrpg/producer/api/countdown', json={'until': 'soon'}).status_code == 400
    assert dm_client.post('/ttrpg/producer/api/countdown', json={}).status_code == 400


def test_clock_reset(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    first = appsettingGet('producer_clock_start', '')
    assert len(first) == 19
    r = dm_client.post('/ttrpg/producer/api/clock/reset')
    assert r.get_json()['ok'] and len(r.get_json()['clock_start']) == 19


def test_marker_while_recording_creates_chapter(dm_client, obs, fresh):
    obs['state']['recording'] = True
    obs['state']['record_timecode'] = '00:12:03.500'
    r = dm_client.post('/ttrpg/producer/api/marker', json={'note': 'Dragon appears'})
    body = r.get_json()
    assert body['ok'] and body['marker']['note'] == 'Dragon appears'
    assert body['marker']['recording'] is True and body['marker']['timecode'] == '00:12:03.500'
    assert ('chapter', 'Dragon appears') in obs['calls']
    assert dm_client.get('/ttrpg/producer/api/markers').get_json()['markers'][-1]['note'] == 'Dragon appears'


def test_marker_without_recording_is_kept_but_no_chapter(dm_client, obs, fresh):
    body = dm_client.post('/ttrpg/producer/api/marker', json={'note': ''}).get_json()
    assert body['ok'] and body['marker']['note'] == 'Marker' and body['marker']['recording'] is False
    assert not any(c[0] == 'chapter' for c in obs['calls'])


def test_marker_chapter_rejection_is_not_fatal(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    obs['state']['recording'] = True

    def boom(name, timeout=3):
        raise obs_ws.ObsRejected(501, 'no chapters in this container')
    monkeypatch.setattr(obs_ws, 'record_chapter', boom)
    body = dm_client.post('/ttrpg/producer/api/marker', json={'note': 'x'}).get_json()
    assert body['ok'] and body['marker']['chapter'] is False and 'container' in body['warning']


def test_markers_capped_and_clearable(dm_client, obs, fresh):
    for i in range(205):
        dm_client.post('/ttrpg/producer/api/marker', json={'note': str(i)})
    ms = dm_client.get('/ttrpg/producer/api/markers').get_json()['markers']
    assert len(ms) == 200 and ms[0]['note'] == '5' and ms[-1]['note'] == '204'
    assert dm_client.delete('/ttrpg/producer/api/markers').get_json() == {'ok': True}
    assert dm_client.get('/ttrpg/producer/api/markers').get_json()['markers'] == []


def test_concurrent_markers_are_all_kept(dm_client, obs, fresh):
    """Two consoles stamping at the same moment: the second save must not
    overwrite the first (read-append-save is serialised)."""
    import threading
    import routers.producer as p
    from sql import appsettingGet, appsettingSet
    appsettingSet('producer_markers', '[]')
    n = 8
    start = threading.Barrier(n)

    def stamp(i):
        start.wait()
        with p._markers_lock:
            rows = p._markers()
            rows.append({'note': str(i)})
            p._save_markers(rows)

    threads = [threading.Thread(target=stamp, args=(i,)) for i in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()
    import json
    assert sorted(m['note'] for m in json.loads(appsettingGet('producer_markers', '[]'))) == sorted(str(i) for i in range(n))


def test_snapshot_program_preview_and_shot(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    obs['state']['preview_scene'] = 'Player - Carl'
    r = dm_client.get('/ttrpg/producer/api/snap/program')
    assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg'
    assert r.headers['cache-control'] == 'no-store' and r.get_data().startswith(b'\xff\xd8')
    assert ('shot', 'ScenePlay Party') in obs['calls']
    dm_client.get('/ttrpg/producer/api/snap/preview')
    assert ('shot', 'Player - Carl') in obs['calls']
    dm_client.get('/ttrpg/producer/api/snap/dm')
    assert ('shot', 'DM - Jankis') in obs['calls']


def test_snapshot_edge_cases(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    _party(monkeypatch)
    assert dm_client.get('/ttrpg/producer/api/snap/nope').status_code == 404
    obs['state']['preview_scene'] = ''
    assert dm_client.get('/ttrpg/producer/api/snap/preview').status_code == 204
    monkeypatch.setattr(obs_ws, 'screenshot', lambda *a, **k: b'')
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204
    obs['flags']['connected'] = False
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204


def test_snapshot_obs_failure_is_204(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    _party(monkeypatch)

    def boom(*a, **k):
        raise obs_ws.ObsUnavailable('timeout')
    monkeypatch.setattr(obs_ws, 'screenshot', boom)
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204


def test_levels(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    import time
    monkeypatch.setattr(obs_ws, 'levels', lambda: ({'ScenePlay Music': [0.5, 0.4]}, time.monotonic() - 0.25))
    body = dm_client.get('/ttrpg/producer/api/levels').get_json()
    assert body['levels'] == {'ScenePlay Music': [0.5, 0.4]} and 200 <= body['age_ms'] <= 2000

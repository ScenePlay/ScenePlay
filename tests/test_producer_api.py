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
    monkeypatch.setattr(p, '_shots_cache', {'at': 0.0, 'key': None, 'value': []})
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


def test_open_turns_studio_mode_on_and_leaves_auto_cam_running(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/session')
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] and body['console_id'] and body['consoles'] == 1
    assert ('studio', True) in obs['calls'] and ('meters', True) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'          # auto-cam is on by default
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['auto_cam_paused'] is False
    assert fresh.producer_active() is True


def test_reset_after_restart_clears_pause(dm_client, obs, fresh, monkeypatch):
    """A restart leaves no console behind, so it may not leave the auto-cam
    pause behind either."""
    from sql import appsettingGet
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': True})   # the producer paused it
    fresh._armed['key'] = 'map'
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '1'
    fresh.reset_after_restart()
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'
    assert fresh._consoles == {} and fresh._armed['key'] is None


def test_connected_hook_is_registered_at_import(fresh):
    import integrations.obs_ws as obs_ws
    assert fresh._on_obs_connected in obs_ws._connected_hooks


def test_connected_hook_reenables_studio_mode_while_console_open(dm_client, obs, fresh, monkeypatch):
    """OBS restarted under a live console: it forgot Studio Mode and the meter
    subscription, and only this hook puts them back."""
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    obs['calls'].clear()
    fresh._on_obs_connected()
    assert ('studio', True) in obs['calls'] and ('meters', True) in obs['calls']


def test_connected_hook_turns_studio_mode_off_when_no_console(obs, fresh):
    """Reconnecting to an OBS still in Studio Mode with every console gone
    (the grace timer died with the old process): put it back."""
    obs['state']['studio_mode'] = True
    fresh._on_obs_connected()
    assert ('studio', False) in obs['calls']
    assert not any(c[0] == 'meters' for c in obs['calls'])
    obs['calls'].clear()
    obs['state']['studio_mode'] = False
    fresh._on_obs_connected()
    assert obs['calls'] == [], 'nothing to reconcile: no console, no Studio Mode'


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
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': True})
    assert r.get_json() == {'ok': True, 'paused': True}
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '1'
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': False})
    assert r.get_json()['paused'] is False and appsettingGet(fresh.PAUSE_KEY, '0') == '0'


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
                    'kind': 'player', 'built': True, 'character_id': 1, 'hotkey': '1'}
    pre = next(s for s in d['shots'] if s['key'] == 'pre')
    assert pre['built'] is False and pre['kind'] == 'special'
    assert d['transitions'] == ['Cut', 'Fade'] and d['transition'] == 'Cut' and d['transition_ms'] == 300
    assert d['consoles'] == 0 and d['armed'] is None and d['auto_cam_paused'] is False
    assert set(d) >= {'studio_mode', 'recording', 'streaming', 'record_timecode', 'stream_timecode',
                      'last_switch', 'countdown_until', 'clock_start', 'markers', 'session'}
    assert d['clock_elapsed_s'] is None and d['countdown_left_s'] is None


def test_state_resolves_both_clocks_server_side(dm_client, obs, fresh, monkeypatch):
    """The stored strings are local time with no offset — a console in another
    timezone could never work them out itself."""
    from datetime import datetime, timedelta
    from sql import appsettingSet
    _party(monkeypatch)
    appsettingSet('producer_clock_start', (datetime.now() - timedelta(minutes=5)).strftime(fresh._TS))
    appsettingSet('producer_countdown_until', (datetime.now() + timedelta(seconds=90)).strftime(fresh._TS))
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert 299 <= d['clock_elapsed_s'] <= 302
    assert 88 <= d['countdown_left_s'] <= 91
    assert len(d['clock_start']) == 19 and len(d['countdown_until']) == 19
    appsettingSet('producer_countdown_until', (datetime.now() - timedelta(seconds=30)).strftime(fresh._TS))
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['countdown_left_s'] < 0


def test_state_carries_only_the_marker_tail(dm_client, obs, fresh):
    """Every console refetches this document on every producer/obs event; the
    full list stays one call away at GET /markers."""
    rows = [{'at': '2026-01-01 00:00:00', 'timecode': '', 'note': str(i),
             'recording': False, 'chapter': False} for i in range(50)]
    fresh._save_markers(rows)
    ms = dm_client.get('/ttrpg/producer/api/state').get_json()['markers']
    assert len(ms) == fresh.STATE_MARKERS and ms[-1]['note'] == '49'
    assert len(dm_client.get('/ttrpg/producer/api/markers').get_json()['markers']) == 50


def test_markers_ignore_a_non_list_value(dm_client, obs, fresh):
    from sql import appsettingSet
    appsettingSet('producer_markers', '{"note": "not a list"}')
    assert dm_client.get('/ttrpg/producer/api/markers').get_json() == {'markers': []}
    assert dm_client.post('/ttrpg/producer/api/marker', json={'note': 'first'}).get_json()['ok']
    assert [m['note'] for m in dm_client.get('/ttrpg/producer/api/markers').get_json()['markers']] == ['first']


def test_shots_cached_for_ttl(obs, fresh, monkeypatch):
    """shots() is on the state and snapshot paths, which a console hits several
    times a second — the party query behind it must not run every time."""
    import routers.obs as ro
    chars = _party(monkeypatch)
    queries = []
    monkeypatch.setattr(ro, '_ordered_party',
                        lambda include_offstage=False: (queries.append(1), chars)[1])
    clock = {'t': 1000.0}
    monkeypatch.setattr(fresh.time, 'monotonic', lambda: clock['t'])
    first = fresh.shots()
    assert len(queries) == 1
    assert fresh.shots() == first and len(queries) == 1        # inside the TTL
    clock['t'] += fresh.SHOTS_TTL_S + 0.1
    assert fresh.shots() == first and len(queries) == 2        # TTL elapsed
    obs['state']['scenes'] = list(obs['state']['scenes']) + ['ScenePlay Pre']
    fresh.shots()
    assert len(queries) == 3, 'a scene built in OBS busts the cache at once'
    fresh.shots()[0]['label'] = 'mutated'
    assert fresh.shots()[0]['label'] != 'mutated', 'callers get copies'


def test_clock_start_renewed_when_stale(dm_client, obs, fresh, monkeypatch):
    """The session clock is this sitting's; a start left over from last week
    would open the console showing a six-day session."""
    from datetime import datetime, timedelta
    from sql import appsettingGet, appsettingSet
    _party(monkeypatch)
    recent = (datetime.now() - timedelta(minutes=30)).strftime(fresh._TS)
    appsettingSet('producer_clock_start', recent)
    dm_client.post('/ttrpg/producer/api/session')
    assert appsettingGet('producer_clock_start', '') == recent, 'same sitting: keep it'
    stale = (datetime.now() - timedelta(seconds=fresh.CLOCK_STALE_S + 60)).strftime(fresh._TS)
    appsettingSet('producer_clock_start', stale)
    dm_client.post('/ttrpg/producer/api/session')
    assert appsettingGet('producer_clock_start', '') != stale
    appsettingSet('producer_clock_start', 'not a timestamp')
    dm_client.post('/ttrpg/producer/api/session')
    assert len(appsettingGet('producer_clock_start', '')) == 19


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


def test_arm_empty_key_clears_armed(dm_client, obs, fresh, monkeypatch):
    """Escape on the console: forget the armed shot, leave OBS's preview where
    it is (that is still what the next Take would put on air)."""
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    obs['calls'].clear()
    r = dm_client.post('/ttrpg/producer/api/arm', json={'key': ''})
    assert r.status_code == 200 and r.get_json() == {'ok': True, 'armed': None}
    assert not any(c[0] == 'preview' for c in obs['calls'])
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] is None


def test_arm_when_disconnected(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    obs['flags']['connected'] = False
    body = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'}).get_json()
    assert body == {'ok': False, 'error': 'OBS is not connected.'}


def test_take_with_nothing_armed(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body == {'ok': False, 'error': 'Nothing armed — arm a shot first (click a tile or press its key), then Take or Auto.'}
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_take_uses_chosen_transition_and_tags_the_cut(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import routers.obs as ro
    emitted = []
    monkeypatch.setattr(ro, '_emit', lambda kind, **x: emitted.append((kind, x)))
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    r = dm_client.post('/ttrpg/producer/api/take', json={'transition': 'Cut'})
    assert r.get_json() == {'ok': True, 'scene': 'ScenePlay Map', 'transition': 'Cut'}
    assert ('transition', 'Cut', 300) in obs['calls'] and ('take',) in obs['calls']   # 300 = OBS's own duration, nothing saved
    assert ('cut', {'target': 'map', 'scene': 'ScenePlay Map', 'by': 'producer'}) in emitted
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] is None


def test_auto_is_gone(dm_client, obs, fresh, monkeypatch):
    """The AUTO button was replaced by the map view toggle; a Take carries the
    Broadcast page's fade settings itself, so a second fade-only route would
    just be a Take that ignored them."""
    _party(monkeypatch)
    # 405, not 404: the SPA catch-all owns GET on unknown paths, so a POST to
    # a route that is gone is refused by method.
    assert dm_client.post('/ttrpg/producer/api/auto', json={'ms': 500}).status_code in (404, 405)


def test_take_obs_rejection_is_reported(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import integrations.obs_ws as obs_ws
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'party'})

    def boom(timeout=3):
        raise obs_ws.ObsRejected(500, 'studio mode is off')
    monkeypatch.setattr(obs_ws, 'trigger_transition', boom)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is False and 'studio mode is off' in body['error']


def test_transition_picker_is_gone(dm_client, obs, fresh, monkeypatch):
    """The console has no transition dropdown of its own any more: the fade is
    set once, on the Broadcast page, and every Take uses it."""
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/transition', json={'name': 'Fade', 'ms': 700})
    assert r.status_code in (404, 405)


def test_broadcast_cut_is_tagged(dm_client, obs, fresh, monkeypatch):
    """Every cut the Broadcast page makes tells switch_scene who did it, so the
    console's Program tile can say "by broadcast page" instead of "automatic"."""
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    seen = []
    monkeypatch.setattr(obs_ws, 'switch_scene', lambda scene, **k: seen.append((scene, k.get('by'))))
    monkeypatch.setattr(obs_ws, 'scene_list', lambda refresh=False: (['ScenePlay Map'], 'ScenePlay Party'))
    monkeypatch.setattr(ro, 'map_scene_name', lambda: 'ScenePlay Map')
    monkeypatch.setattr(ro, '_special_scene', lambda special: '')
    r = dm_client.post('/ttrpg/obs/api/cut/map')
    assert r.status_code == 200 and seen == [('ScenePlay Map', 'broadcast')]

    seen.clear()                                   # the manual scene buttons
    monkeypatch.setattr(ro, '_after_switch', lambda scene: None)
    r = dm_client.post('/ttrpg/obs/api/switch', json={'scene': 'ScenePlay Map'})
    assert r.status_code == 200 and seen == [('ScenePlay Map', 'broadcast')]

    seen.clear()                                   # featuring a player
    monkeypatch.setattr(ro, 'party_scene_name', lambda: 'ScenePlay Party')
    monkeypatch.setattr(ro, '_sync_party_scene', lambda featured_id=None: {'warnings': []})
    monkeypatch.setattr(obs_ws, 'current_state', lambda: {'current_scene': 'ScenePlay Map'})
    _payload, err = ro._do_feature(1)
    assert err is None and seen == [('ScenePlay Party', 'broadcast')]


def test_second_take_without_rearming_is_refused(dm_client, obs, fresh, monkeypatch):
    """After a Take, Preview still names the scene that is now Program; the
    console must not fire a second, empty-target cut."""
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    assert dm_client.post('/ttrpg/producer/api/take', json={}).get_json()['ok'] is True
    obs['state']['current_scene'] = 'ScenePlay Map'          # what OBS reports after the cut
    obs['calls'].clear()
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body == {'ok': False, 'error': 'Nothing armed — arm a shot first (click a tile or press its key), then Take or Auto.'}
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_take_of_a_preview_armed_inside_obs(dm_client, obs, fresh, monkeypatch):
    """Preview moved from OBS's own UI (event, no console arm) and differs from
    Program: a Take is legitimate and reports the scene."""
    _party(monkeypatch)
    obs['state']['preview_scene'] = 'Player - Carl'
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is True and body['scene'] == 'Player - Carl'


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
    # The first 200 go straight into the store: stamping them through the API
    # would fan 200 `producer` events into the session-wide hub (and starve
    # every other subscriber, tests/test_events.py included). Five go the real
    # way, which is what pushes the list over the cap.
    fresh._save_markers([{'at': '2026-01-01 00:00:00', 'timecode': '', 'note': str(i),
                          'recording': False, 'chapter': False} for i in range(200)])
    for i in range(200, 205):
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


# ── closeup scenes ───────────────────────────────────────────────────────────

@pytest.fixture()
def closeup_rig(obs, monkeypatch):
    """Party scene already built for Carl (cam + overlay) and the DM (cam only);
    the per-character closeup scenes do not exist yet."""
    import integrations.obs_ws as obs_ws
    scenes = {'ScenePlay Party': {'Player - Carl Cam': 11, 'Player - Carl Overlay': 12, 'DM - Jankis Cam': 13}}
    ids = iter(range(100, 200))

    def scene_items(scene, timeout=3):
        if scene not in scenes:
            raise obs_ws.ObsRejected(600, 'no such scene')
        return dict(scenes[scene])

    def ensure_scene(scene, timeout=3):
        scenes.setdefault(scene, {})
        obs['calls'].append(('ensure_scene', scene))

    def ensure_item(scene, source, timeout=5):
        item = scenes[scene].get(source)
        if item is None:
            item = scenes[scene][source] = next(ids)
        obs['calls'].append(('ensure_item', scene, source))
        return item

    monkeypatch.setattr(obs_ws, 'scene_items', scene_items)
    monkeypatch.setattr(obs_ws, 'ensure_scene', ensure_scene)
    monkeypatch.setattr(obs_ws, 'ensure_item', ensure_item)
    monkeypatch.setattr(obs_ws, 'ensure_nested_scene', lambda parent, child, timeout=5: obs['calls'].append(('nest', parent, child)) or 900)
    monkeypatch.setattr(obs_ws, 'place_item', lambda scene, item, rect, timeout=3: obs['calls'].append(('place', scene, item, rect)))
    monkeypatch.setattr(obs_ws, 'set_item_enabled', lambda scene, item, on, timeout=3: obs['calls'].append(('enable', scene, item, on)))
    obs['state']['base_width'], obs['state']['base_height'] = 1280, 720
    return scenes


def test_build_closeups_reuses_the_party_inputs_full_frame(dm_client, obs, fresh, closeup_rig, monkeypatch):
    _party(monkeypatch, names=('Carl', 'Donut'))          # Donut has no tile in the party scene yet
    r = dm_client.post('/ttrpg/producer/api/build-closeups')
    body = r.get_json()
    assert body['ok'] is True
    assert body['built'] == ['Player - Carl', 'DM - Jankis'] and body['skipped'] == ['Donut']
    assert 'Player - Carl' in closeup_rig and 'DM - Jankis' in closeup_rig and 'Player - Donut' not in closeup_rig
    assert closeup_rig['Player - Carl'] == {'Player - Carl Cam': 100, 'Player - Carl Overlay': 101}
    assert closeup_rig['DM - Jankis'] == {'DM - Jankis Cam': 102}
    full = {'x': 0, 'y': 0, 'w': 1280, 'h': 720}
    assert ('place', 'Player - Carl', 100, full) in obs['calls'] and ('place', 'Player - Carl', 101, full) in obs['calls']
    assert ('enable', 'DM - Jankis', 102, True) in obs['calls']


def test_build_closeups_is_idempotent(dm_client, obs, fresh, closeup_rig, monkeypatch):
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/build-closeups')
    first = dict(closeup_rig['Player - Carl'])
    dm_client.post('/ttrpg/producer/api/build-closeups')
    assert closeup_rig['Player - Carl'] == first          # same items, nothing duplicated


def test_build_closeups_refreshes_the_shot_list(dm_client, obs, fresh, closeup_rig, monkeypatch):
    """The shots cache must not keep reporting 'not built' after a build."""
    _party(monkeypatch)
    obs['state']['scenes'] = ['ScenePlay Party', 'ScenePlay Map']      # no closeup scenes yet
    assert next(s for s in dm_client.get('/ttrpg/producer/api/state').get_json()['shots'] if s['key'] == 'char:1')['built'] is False
    dm_client.post('/ttrpg/producer/api/build-closeups')
    obs['state']['scenes'] = obs['state']['scenes'] + ['Player - Carl', 'DM - Jankis']
    assert next(s for s in dm_client.get('/ttrpg/producer/api/state').get_json()['shots'] if s['key'] == 'char:1')['built'] is True


def test_build_closeups_error_paths(dm_client, obs, fresh, closeup_rig, monkeypatch):
    import integrations.obs_ws as obs_ws
    _party(monkeypatch)
    obs['flags']['connected'] = False
    assert dm_client.post('/ttrpg/producer/api/build-closeups').get_json() == {'ok': False, 'error': 'OBS is not connected.'}
    obs['flags']['connected'] = True

    def boom(scene, timeout=3):
        raise obs_ws.ObsRejected(500, 'nope')
    monkeypatch.setattr(obs_ws, 'ensure_scene', boom)
    body = dm_client.post('/ttrpg/producer/api/build-closeups').get_json()
    assert body['ok'] is False and 'nope' in body['error']


def test_taking_a_player_shot_features_them_in_the_party_scene(dm_client, obs, fresh, monkeypatch):
    import routers.obs as ro
    _party(monkeypatch)
    obs['state']['scenes'] = obs['state']['scenes'] + ['Player - Carl']
    featured = []
    monkeypatch.setattr(ro, '_sync_party_scene', lambda featured_id=None: featured.append(featured_id) or {'warnings': []})
    monkeypatch.setattr(ro, '_set_featured', lambda cid: featured.append(('set', cid)))
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'char:1'})
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is True and body['scene'] == 'Player - Carl'
    assert featured == [1, ('set', 1)]
    featured.clear()
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    dm_client.post('/ttrpg/producer/api/take', json={})
    assert featured == []                                   # only player shots feature


def test_feature_failure_does_not_fail_the_take(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    _party(monkeypatch)
    obs['state']['scenes'] = obs['state']['scenes'] + ['Player - Carl']

    def boom(featured_id=None):
        raise obs_ws.ObsRejected(500, 'layout failed')
    monkeypatch.setattr(ro, '_sync_party_scene', boom)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'char:1'})
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is True and 'layout failed' in body['warning']


def test_build_party_also_builds_closeups(dm_client, obs, fresh, monkeypatch):
    import routers.obs as ro
    import routers.producer as p
    calls = []
    monkeypatch.setattr(ro, '_sync_party_scene', lambda featured_id=None: {'scene': 'ScenePlay Party', 'tiles': [], 'warnings': []})
    monkeypatch.setattr(ro, 'ensure_map_scene', lambda: ('ScenePlay Map', []))
    monkeypatch.setattr(ro, 'ensure_show_scenes', lambda: ({}, []))
    monkeypatch.setattr(ro, '_build_audio', lambda w, h, warnings: None)
    monkeypatch.setattr(ro, '_scene_inventory', lambda names: {})
    # build-party also starts the feed/cam watchers — real timer threads that
    # would outlive this test and bleed into the rest of the session
    monkeypatch.setattr(ro, 'start_feed_watch', lambda app_obj: None)
    monkeypatch.setattr(p, 'build_closeups', lambda: calls.append('closeups') or {'built': ['Player - Carl'], 'skipped': []})
    r = dm_client.post('/ttrpg/obs/api/build-party')
    assert r.status_code == 200 and calls == ['closeups']
    assert r.get_json()['closeups'] == ['Player - Carl']


def test_build_closeups_carries_the_party_audio(dm_client, obs, fresh, closeup_rig, monkeypatch):
    """Like Build does for Map / Pre / Post: the party scene rides inside each
    closeup off-canvas, so every voice and the music survive the cut."""
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/build-closeups')
    nested = [c[1:] for c in obs['calls'] if c[0] == 'nest']
    assert nested == [('Player - Carl', 'ScenePlay Party'), ('DM - Jankis', 'ScenePlay Party')]
    off_canvas = {'x': 1280 + 100, 'y': 0, 'w': 320, 'h': 180}
    assert ('place', 'Player - Carl', 900, off_canvas) in obs['calls'] and ('enable', 'Player - Carl', 900, True) in obs['calls']


def test_shots_carry_the_broadcast_page_hotkeys(dm_client, obs, fresh, monkeypatch):
    """1–9 count the players in tile order like the Broadcast page; 0 is the
    whole party; B map, I intermission; pre/post have no key."""
    _party(monkeypatch, names=('Carl', 'Donut'))
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert [(s['key'], s['hotkey']) for s in d['shots']] == [
        ('party', '0'), ('map', 'B'), ('char:1', '1'), ('char:2', '2'), ('dm', '3'),
        ('pre', ''), ('intermission', 'I'), ('post', '')]


def test_state_defaults_to_the_broadcast_page_transition(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingSet
    _party(monkeypatch)
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert d['transition'] == 'Cut' and d['transition_ms'] == 300          # nothing saved: OBS's own
    appsettingSet('obs_transition', 'Fade')
    appsettingSet('obs_transition_ms', '700')
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert d['transition'] == 'Fade' and d['transition_ms'] == 700


def test_state_carries_the_map_mode(dm_client, obs, fresh, monkeypatch):
    """The console's AUTO / 2D / 3D button is the battle map's, so it paints
    from the same setting and follows a change made from either page."""
    from sql import appsettingSet
    _party(monkeypatch)
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['map_mode'] == 'auto'
    appsettingSet('obs_map_mode', '2d')
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['map_mode'] == '2d'
    r = dm_client.post('/ttrpg/obs/api/map-mode', json={})          # the button's own call
    assert r.get_json()['mode'] == '3d'
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['map_mode'] == '3d'


def test_take_without_a_transition_uses_the_saved_default(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingSet
    _party(monkeypatch)
    appsettingSet('obs_transition', 'Fade')
    appsettingSet('obs_transition_ms', '700')
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is True and body['transition'] == 'Fade'
    assert ('transition', 'Fade', 700) in obs['calls']


# ── spotlight (feature inside the party scene) ───────────────────────────────

@pytest.fixture()
def spot(monkeypatch):
    """Recording stubs of the party-layout machinery. `_do_feature` and
    `_unfeature` (the Broadcast page's handlers) are poisoned: they cut
    program to the party scene, which the console's spotlight must never do."""
    import routers.obs as ro
    calls = []

    def never(*a, **k):
        raise AssertionError('the console spotlight must not cut program')
    monkeypatch.setattr(ro, '_do_feature', never)
    monkeypatch.setattr(ro, '_unfeature', never)
    monkeypatch.setattr(ro, '_sync_party_scene', lambda featured_id=None: calls.append(('layout', featured_id)) or {'warnings': []})
    monkeypatch.setattr(ro, '_set_featured', lambda cid: calls.append(('set', cid)))
    monkeypatch.setattr(ro, '_cancel_return', lambda: calls.append(('cancel_return',)))
    monkeypatch.setattr(ro, 'featured_id', lambda: next((c[1] for c in reversed(calls) if c[0] == 'set'), None))
    monkeypatch.setattr(ro, '_emit', lambda kind, **x: calls.append(('emit', kind)))
    return calls


def test_spotlight_features_a_player_without_cutting(dm_client, obs, fresh, spot, monkeypatch):
    _party(monkeypatch)
    obs['state']['current_scene'] = 'ScenePlay Map'            # program is elsewhere and must stay there
    r = dm_client.post('/ttrpg/producer/api/spotlight', json={'key': 'char:1'})
    assert r.get_json() == {'ok': True, 'featured': 'char:1', 'featured_id': 1}
    assert spot == [('layout', 1), ('set', 1), ('emit', 'feature')]
    assert not any(c[0] == 'switch' for c in obs['calls'])
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['featured_id'] == 1


def test_spotlight_group_evens_the_table_without_cutting(dm_client, obs, fresh, spot, monkeypatch):
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/spotlight', json={'key': ''})
    assert r.get_json() == {'ok': True, 'featured': None, 'featured_id': None}
    assert spot == [('layout', None), ('set', None), ('cancel_return',), ('emit', 'group')]


def test_spotlight_rejects_specials_and_disconnected(dm_client, obs, fresh, spot, monkeypatch):
    _party(monkeypatch)
    assert dm_client.post('/ttrpg/producer/api/spotlight', json={'key': 'map'}).status_code == 400
    assert dm_client.post('/ttrpg/producer/api/spotlight', json={'key': 'nope'}).status_code == 400
    obs['flags']['connected'] = False
    assert dm_client.post('/ttrpg/producer/api/spotlight', json={'key': 'char:1'}).get_json() == {'ok': False, 'error': 'OBS is not connected.'}
    assert spot == []


def test_spotlight_reports_a_refused_layout(dm_client, obs, fresh, spot, monkeypatch):
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    _party(monkeypatch)

    def boom(featured_id=None):
        raise obs_ws.ObsRejected(500, 'busy')
    monkeypatch.setattr(ro, '_sync_party_scene', boom)
    body = dm_client.post('/ttrpg/producer/api/spotlight', json={'key': 'dm'}).get_json()
    assert body == {'ok': False, 'error': 'OBS refused: busy'}


def test_state_carries_the_scene_links(dm_client, obs, fresh, monkeypatch):
    """The DM screen's scene → OBS scene links, so a tile can show where a
    ScenePlay activation will cut OBS (and whether the link is live at all)."""
    from models.ttrpg import tblObsSceneMap
    from sql import appsettingSet
    db.session.add(tblObsSceneMap(entity_type='scene', entity_id=25, entity_key='', scene_name='ScenePlay Pre'))
    db.session.commit()
    appsettingSet('obs_enabled', '1'); appsettingSet('obs_scene_link', '0')
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert d['scene_links'] == {'25': 'ScenePlay Pre'} and d['scene_links_live'] is False
    appsettingSet('obs_scene_link', '1')
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['scene_links_live'] is True


# ── connecting to OBS from the console ───────────────────────────────────────

def test_state_carries_the_obs_connection_info(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    from sql import appsettingSet
    appsettingSet('obs_enabled', '0'); appsettingSet('obs_host', '10.0.4.33'); appsettingSet('obs_port', '4455')
    monkeypatch.setattr(obs_ws, 'state', lambda: 'disabled')
    monkeypatch.setattr(obs_ws, 'last_error', lambda: '2026-09-15 10:00:00|connect|refused')
    d = dm_client.get('/ttrpg/producer/api/state').get_json()
    assert d['obs'] == {'enabled': False, 'state': 'disabled', 'error': 'refused', 'target': '10.0.4.33:4455'}
    appsettingSet('obs_enabled', '1'); monkeypatch.setattr(obs_ws, 'state', lambda: 'connected'); monkeypatch.setattr(obs_ws, 'last_error', lambda: '')
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['obs'] == {'enabled': True, 'state': 'connected', 'error': '', 'target': '10.0.4.33:4455'}


def test_connect_enables_obs_control_when_it_is_off(dm_client, obs, fresh, monkeypatch):
    import routers.obs as ro
    from sql import appsettingSet
    appsettingSet('obs_enabled', '0')
    calls = []
    monkeypatch.setattr(ro, 'enable_obs', lambda: calls.append('enable') or {'ok': True, 'enabled': True, 'message': 'OBS control enabled — connecting.'})
    r = dm_client.post('/ttrpg/producer/api/obs/connect')
    assert r.get_json() == {'ok': True, 'enabled': True, 'message': 'OBS control enabled — connecting.'}
    assert calls == ['enable']


def test_connect_reconnects_when_control_is_already_on(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    from sql import appsettingSet
    appsettingSet('obs_enabled', '1')
    calls = []
    monkeypatch.setattr(ro, 'enable_obs', lambda: calls.append('enable'))
    monkeypatch.setattr(obs_ws, 'restart', lambda: calls.append('restart'))
    r = dm_client.post('/ttrpg/producer/api/obs/connect')
    assert r.get_json() == {'ok': True, 'enabled': True, 'message': 'Reconnecting to OBS.'}
    assert calls == ['restart']


def test_enable_obs_is_what_the_toggle_uses(dm_client, obs, fresh, monkeypatch):
    """The Broadcast page's Enable and the console's Connect share one path."""
    import core.config as config
    import integrations.obs_ws as obs_ws
    import integrations.relay_guard as relay_guard
    import routers.obs as ro
    from sql import appsettingGet, appsettingSet
    monkeypatch.setattr(config, 'INTEGRATIONS', True)
    appsettingSet('obs_enabled', '0'); appsettingSet('obs_boot_tripped', 'yesterday')
    calls = []
    monkeypatch.setattr(obs_ws, 'start', lambda app: calls.append('start'))
    monkeypatch.setattr(ro, 'start_feed_watch', lambda app: calls.append('feed'))
    monkeypatch.setattr(ro, 'start_dice_watch', lambda app: calls.append('dice'))
    monkeypatch.setattr(relay_guard, 'arm', lambda *a, **k: calls.append('arm'))
    monkeypatch.setattr(relay_guard, 'disarm_after_grace', lambda *a, **k: calls.append('disarm'))
    monkeypatch.setattr(ro, '_emit', lambda *a, **k: None)
    out = ro.enable_obs()
    assert out == {'ok': True, 'enabled': True, 'message': 'OBS control enabled — connecting.'}
    assert calls == ['arm', 'start', 'feed', 'dice', 'disarm']
    assert appsettingGet('obs_enabled', '0') == '1' and appsettingGet('obs_boot_tripped', 'x') == ''
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    assert ro.enable_obs()['ok'] is False


def test_state_scenes_are_the_active_sessions_campaign_scenes(dm_client, obs, fresh, monkeypatch):
    """Same list the DM's session and battle-map screens show: the active
    session's campaign, enabled scenes only, in DM order, with the OBS link."""
    from models.scenes import tblscenes
    from models.ttrpg import tblSessions, tblObsSceneMap
    db.session.add_all([
        tblscenes(sceneName='Tavern', active=1, orderBy=2, campaign_id=7),
        tblscenes(sceneName='Forest', active=1, orderBy=1, campaign_id=7),
        tblscenes(sceneName='Retired', active=0, orderBy=3, campaign_id=7),
        tblscenes(sceneName='Other campaign', active=1, orderBy=1, campaign_id=8),
    ])
    db.session.commit()
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['scenes'] == []      # no active session yet
    db.session.add(tblSessions(title='Night 3', session_number=3, campaign_id=7, status='active', created_at='2026-09-15 19:00:00'))
    db.session.commit()
    forest = tblscenes.query.filter_by(sceneName='Forest').first()
    db.session.add(tblObsSceneMap(entity_type='scene', entity_id=forest.scene_ID, entity_key='', scene_name='ScenePlay Map'))
    db.session.commit()
    scenes = dm_client.get('/ttrpg/producer/api/state').get_json()['scenes']
    assert [s['sceneName'] for s in scenes] == ['Forest', 'Tavern']
    assert scenes[0]['obs_scene'] == 'ScenePlay Map' and scenes[1]['obs_scene'] is None
    assert set(scenes[0]) == {'scene_ID', 'sceneName', 'obs_scene'}

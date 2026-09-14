"""P6 relay admin: page-data endpoints (/api/v1/relay/{page,party,rolls}),
the verbatim /ttrpg/relay JSON paths (health, presence, the form endpoints
turned {ok, message}), the server-to-server calls the portal makes, and the
SSE `relay` snapshot. No network: `requests` is faked per test."""
import json
import types

import pytest

from core.db import db
from tests.conftest import auth


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f'HTTP {self.status_code}')


@pytest.fixture()
def relay(monkeypatch, legacy_app):
    """Settings dict standing in for tblAppSettings + a fake relay portal
    (`routes` maps path suffix -> body or a callable(url, kw) -> _Resp)."""
    import core.config as config
    import routers.relay_admin as ra
    monkeypatch.setattr(config, 'INTEGRATIONS', True)     # conftest runs with SP_INTEGRATIONS=0
    settings = {}
    monkeypatch.setattr(ra, 'appsettingGet', lambda k, d=None: settings.get(k, d))
    monkeypatch.setattr(ra, 'appsettingSet', lambda k, v, *a: settings.__setitem__(k, str(v)))
    calls = []
    routes = {}

    def _find(url):
        for suffix, body in routes.items():
            if url.endswith(suffix):
                return body
        return None

    def fake_get(url, **kw):
        calls.append(('GET', url, kw))
        body = _find(url)
        if body is None:
            return _Resp({'error': 'not found'}, 404)
        return body(url, kw) if callable(body) else _Resp(body)

    def fake_post(url, **kw):
        calls.append(('POST', url, kw))
        body = _find(url)
        if body is None:
            return _Resp({'error': 'not found'}, 404)
        return body(url, kw) if callable(body) else _Resp(body)

    monkeypatch.setattr(ra.requests, 'get', fake_get)
    monkeypatch.setattr(ra.requests, 'post', fake_post)
    pushes = []
    fake_bc = types.SimpleNamespace(
        push_all_characters=lambda: pushes.append('chars'),
        push_session_users=lambda: pushes.append('users'),
        push_character_feeds=lambda: pushes.append('feeds'),
        push_library=lambda: pushes.append('library'),
        get_presence=lambda: {},
    )
    import sys
    from tests.conftest import fake_module
    fake_module(monkeypatch, 'integrations.relay_broadcaster', fake_bc)
    ws_calls = []
    fake_ws = types.SimpleNamespace(start=lambda app: ws_calls.append('start'),
                                    stop=lambda: ws_calls.append('stop'),
                                    restart=lambda: ws_calls.append('restart'),
                                    connected=lambda: False, state=lambda: 'disabled')
    fake_module(monkeypatch, 'integrations.relay_ws', fake_ws)
    return types.SimpleNamespace(app=legacy_app, settings=settings, routes=routes, calls=calls,
                                 pushes=pushes, ws_calls=ws_calls, fake_bc=fake_bc)


def _enabled(relay, sid='sess-1', code='ABC123'):
    relay.settings.update({'relay_enabled': '1', 'relay_url': 'https://relay.example',
                           'relay_secret': 's3cret', 'relay_session_id': sid,
                           'relay_session_code': code})


# ── auth matrix ───────────────────────────────────────────────────────────────

def test_dm_only_everywhere(client, player_token):
    for p in ('/api/v1/relay/page', '/api/v1/relay/party', '/api/v1/relay/rolls',
              '/ttrpg/relay/api/health', '/ttrpg/relay/api/presence'):
        assert client.get(p).status_code == 401, p
        r = client.get(p, headers=auth(player_token))
        assert r.status_code == 403 and r.json()['code'] == 'dm_required', p
    for p in ('/ttrpg/relay/toggle', '/ttrpg/relay/save-config', '/ttrpg/relay/generate-code',
              '/ttrpg/relay/reuse-code', '/ttrpg/relay/sync-characters', '/ttrpg/relay/clear-rolls'):
        assert client.post(p, json={}).status_code == 401, p
        r = client.post(p, json={}, headers=auth(player_token))
        assert r.status_code == 403 and r.json()['code'] == 'dm_required', p


# ── page data ─────────────────────────────────────────────────────────────────

def test_page_disabled_never_leaks_the_secret(relay, dm):
    relay.settings.update({'relay_secret': 'topsecret', 'relay_url': 'https://relay.example'})
    r = relay.app.test_client(user=dm).get('/api/v1/relay/page')
    assert r.status_code == 200
    d = r.get_json()
    assert d['cfg']['enabled'] == '0' and d['cfg']['secret_set'] is True
    assert 'secret' not in d['cfg'] and 'topsecret' not in r.text
    assert d['logged_in'] == [] and d['sync_age'] is None
    assert d['cfg']['audio_bitrate'] == '128' and d['cfg']['audio_profile'] == 'low'
    assert not relay.calls                     # disabled: no portal round-trips


def test_page_lists_joined_players_with_presence_and_spectators(relay, dm):
    _enabled(relay)
    relay.settings['relay_last_sync'] = '2000-01-01 00:00:00'
    relay.routes['/session/sess-1/sync'] = {'characters': [
        {'player_name': 'Hero', 'username': 'alice', 'display_name': 'Alice', 'has_joined': True,
         'sheet_json': json.dumps({'class': 'Fighter', 'level': 3}), 'hp_current': 10, 'hp_max': 40,
         'joined_at': '2026-01-02T10:11:12'},
        {'player_name': 'Ghost', 'username': 'bob', 'has_joined': False},
        {'player_name': 'Mage', 'username': 'carol', 'display_name': 'Carol', 'has_joined': True,
         'sheet_json': '{}', 'hp_current': 5, 'hp_max': 5},
        {'player_name': 'Bard', 'username': 'dave', 'display_name': 'Dave', 'has_joined': True,
         'sheet_json': 'not json', 'hp_current': 0, 'hp_max': 0},
    ]}
    # keyed by username (alice), display name (Carol) and character name (Bard)
    relay.routes['/session/sess-1/presence'] = {'presence': {'alice': 5, 'Carol': 10, 'Bard': 95,
                                                             'Watcher': 200}}
    d = relay.app.test_client(user=dm).get('/api/v1/relay/page').get_json()
    assert d['sync_age'] > 90
    names = [p['player_name'] for p in d['logged_in']]
    assert names == ['Hero', 'Mage', 'Bard', 'Watcher']
    hero, mage, bard, watcher = d['logged_in']
    assert hero['online'] is True and hero['char_class'] == 'Fighter' and hero['level'] == 3
    assert hero['hp_pct'] == 25 and hero['joined_at'] == '2026-01-02 10:11'
    assert mage['online'] is True and mage['char_class'] == '—' and mage['hp_pct'] == 100
    assert bard['online'] is False and bard['hp_max'] == 1 and bard['hp_pct'] == 0   # stale + bad sheet
    assert watcher['no_character'] is True and watcher['online'] is False
    assert all(kw['headers']['X-Relay-Secret'] == 's3cret' for _, _, kw in relay.calls)


def test_page_survives_an_unreachable_relay(relay, dm):
    _enabled(relay)

    def boom(url, kw):
        raise ConnectionError('down')
    relay.routes['/sync'] = boom
    relay.routes['/presence'] = boom
    d = relay.app.test_client(user=dm).get('/api/v1/relay/page').get_json()
    assert d['logged_in'] == [] and d['cfg']['code'] == 'ABC123'


def test_party_page(relay, dm):
    _enabled(relay)
    relay.routes['/session/sess-1/sync'] = {'characters': [
        {'id': 7, 'player_name': 'Hero', 'has_joined': True,
         'sheet_json': json.dumps({'name': 'Hero', 'class': 'Rogue', 'ac': 14}),
         'hp_current': 30, 'hp_max': 30, 'updated_at': '2026-03-04T05:06:07'},
        {'id': 8, 'player_name': 'Nope', 'has_joined': False},
    ]}
    d = relay.app.test_client(user=dm).get('/api/v1/relay/party').get_json()
    assert d['error'] is None and 'secret' not in d['cfg']
    assert [c['char_id'] for c in d['party']] == [7]
    c = d['party'][0]
    assert c['sheet']['class'] == 'Rogue' and c['hp_pct'] == 100 and c['updated_at'] == '2026-03-04 05:06'


def test_party_page_reports_relay_error(relay, dm):
    _enabled(relay)
    relay.routes['/sync'] = lambda url, kw: _Resp({}, 503)
    d = relay.app.test_client(user=dm).get('/api/v1/relay/party').get_json()
    assert d['party'] == [] and 'HTTP 503' in d['error']


def test_rolls_page(relay, dm):
    from models.ttrpg import tblSessions
    from models.tblRollLog import tblRollLog
    sess = tblSessions(title='S', status='active', created_at='2026-01-01 00:00:00')
    db.session.add(sess)
    db.session.flush()
    for i in range(3):
        db.session.add(tblRollLog(session_id=sess.session_id, player_name='Hero', roll_expr='1d20+2',
                                  result=10 + i, breakdown=f'[{8 + i}]+2',
                                  rolled_at=f'2026-01-01 12:0{i}:00'))
    db.session.commit()
    c = relay.app.test_client(user=dm)
    assert c.get('/api/v1/relay/rolls').get_json() == {'entries': [], 'session_id': ''}
    relay.settings['relay_session_id'] = str(sess.session_id)
    d = c.get('/api/v1/relay/rolls').get_json()
    assert d['session_id'] == str(sess.session_id)
    assert [e['result'] for e in d['entries']] == [12, 11, 10]       # newest first
    assert set(d['entries'][0]) == {'id', 'rolled_at', 'player_name', 'roll_expr', 'result', 'breakdown'}
    relay.settings['relay_session_id'] = 'not-an-int'                 # portal-style uuid: no local rows
    assert c.get('/api/v1/relay/rolls').get_json()['entries'] == []


# ── verbatim JSON paths ───────────────────────────────────────────────────────

def test_health_idle_and_stalled(relay, dm):
    c = relay.app.test_client(user=dm)
    assert c.get('/ttrpg/relay/api/health').get_json() == {'enabled': False, 'ok': True, 'problems': []}
    _enabled(relay)
    d = c.get('/ttrpg/relay/api/health').get_json()
    assert d['enabled'] and not d['ok'] and d['sync_age'] is None and 'not completed' in d['problems'][0]
    assert d['transport'] == 'polling (disabled)'
    relay.settings['relay_last_sync'] = '2000-01-01 00:00:00'
    relay.settings['relay_push_last_drop'] = '2000-01-01 00:00:00|library|HTTP 500'   # old: self-clears
    d = c.get('/ttrpg/relay/api/health').get_json()
    assert len(d['problems']) == 1 and 'stalled' in d['problems'][0]


def test_health_recent_drop_variants(relay, dm, monkeypatch):
    from datetime import datetime, timezone
    _enabled(relay)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    relay.settings['relay_last_sync'] = now
    c = relay.app.test_client(user=dm)
    relay.settings['relay_push_last_drop'] = f'{now}|library|HTTP 500'
    d = c.get('/ttrpg/relay/api/health').get_json()
    assert d['ok'] is False and 'library: HTTP 500' in d['problems'][0]
    relay.settings['relay_push_last_drop'] = f'{now}|map|/session/sess-1/map: 404'
    assert 'no longer knows this session' in c.get('/ttrpg/relay/api/health').get_json()['problems'][0]
    relay.settings['relay_push_last_drop'] = f'{now}|map|/session/OTHER/map: 404'   # not our session
    assert c.get('/ttrpg/relay/api/health').get_json()['ok'] is True


def test_presence(relay, dm):
    c = relay.app.test_client(user=dm)
    assert c.get('/ttrpg/relay/api/presence').get_json() == {'enabled': False, 'online': {}}
    _enabled(relay)
    relay.routes['/presence'] = {'presence': {'Hero': 3, 'Slow': 95, 'Odd': None}}
    assert c.get('/ttrpg/relay/api/presence').get_json() == \
        {'enabled': True, 'online': {'Hero': True, 'Slow': False, 'Odd': False}}


def test_relay_snapshot_feeds_the_sse_topic(relay):
    import routers.relay_admin as ra
    import core.events as events
    assert 'relay' in events._derived and events._derived['relay'][0] is ra.relay_snapshot
    s = ra.relay_snapshot()
    assert s['enabled'] is False and s['online'] == {} and s['code'] == ''
    _enabled(relay)
    relay.fake_bc.get_presence = lambda: {'Hero': 1, 'Gone': 500}
    s = ra.relay_snapshot()
    assert s['enabled'] and s['online'] == {'Hero': True, 'Gone': False} and s['code'] == 'ABC123'
    assert set(s) >= {'ok', 'problems', 'sync_age', 'transport', 'last_sync', 'ts'}


# ── mutations ─────────────────────────────────────────────────────────────────

def test_save_config_json(relay, dm):
    relay.settings.update({'relay_url': 'https://old', 'relay_secret': 'old'})
    c = relay.app.test_client(user=dm)
    r = c.post('/ttrpg/relay/save-config', json={'relay_url': 'https://new ', 'relay_secret': '',
                                                  'relay_audio_bitrate': '96', 'relay_audio_profile': 'smooth',
                                                  'relay_audio_gain': '999'})
    assert r.status_code == 200
    assert r.get_json() == {'ok': True, 'reconnecting': True, 'message': 'Relay configuration saved.'}
    assert relay.settings['relay_url'] == 'https://new' and relay.settings['relay_secret'] == 'old'
    assert relay.settings['relay_audio_enabled'] == '0'               # checkbox absent = off
    assert relay.settings['relay_audio_bitrate'] == '96'
    assert relay.settings['relay_audio_profile'] == 'smooth'
    assert relay.settings['relay_audio_gain'] == '50'                 # invalid -> default
    assert relay.ws_calls == ['restart']
    # unchanged url/secret: no reconnect; checkbox on
    r = c.post('/ttrpg/relay/save-config', data={'relay_url': 'https://new', 'relay_audio_enabled': '1'})
    assert r.get_json()['reconnecting'] is False and relay.settings['relay_audio_enabled'] == '1'
    assert relay.ws_calls == ['restart']


def test_integrations_off_never_reaches_the_relay(relay, dm, monkeypatch):
    """SP_INTEGRATIONS=0 (a dev instance on a DB copy carrying the live
    relay URL + secret): enable / New Session / Reuse / Sync are refused
    before any portal call; disabling stays local and still works."""
    import core.config as config
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    _enabled(relay)
    relay.settings['relay_enabled'] = '0'
    c = relay.app.test_client(user=dm)
    for p in ('/ttrpg/relay/toggle', '/ttrpg/relay/generate-code', '/ttrpg/relay/reuse-code',
              '/ttrpg/relay/sync-characters'):
        r = c.post(p, json={'session_mode': 'new'})
        assert r.status_code == 200 and r.get_json()['ok'] is False, p
        assert 'SP_INTEGRATIONS=0' in r.get_json()['message'], p
    assert relay.settings['relay_enabled'] == '0' and relay.settings['relay_session_code'] == 'ABC123'
    assert not relay.calls and not relay.pushes and not relay.ws_calls
    relay.settings['relay_enabled'] = '1'
    r = c.post('/ttrpg/relay/toggle', json={})
    assert r.get_json() == {'ok': True, 'message': 'Relay disabled.', 'enabled': False, 'code': 'ABC123'}
    assert relay.settings['relay_enabled'] == '0' and relay.ws_calls == ['stop']


def test_sync_characters_pushes_everything(relay, dm):
    r = relay.app.test_client(user=dm).post('/ttrpg/relay/sync-characters')
    assert r.status_code == 200 and r.get_json()['ok'] is True
    assert 'pushed to relay' in r.get_json()['message']
    assert relay.pushes == ['chars', 'users', 'feeds', 'library']


def test_clear_rolls(relay, dm, monkeypatch):
    from models.ttrpg import tblDiceRolls
    import sql
    store = {}
    monkeypatch.setattr(sql, 'appsettingSet', lambda k, v, *a: store.__setitem__(k, v))
    db.session.add(tblDiceRolls(char_name='A', expression='1d6', label='', dice_json='[4]',
                                modifier=0, total=4, adv_mode='normal', rolled_at='2026-01-01 12:00:00'))
    db.session.commit()
    r = relay.app.test_client(user=dm).post('/ttrpg/relay/clear-rolls')
    assert r.status_code == 200 and r.get_json()['ok'] and r.get_json()['removed'] == 1
    assert 'cleared' in r.get_json()['message'] and 'relay_roll_cleared_at' in store
    assert tblDiceRolls.query.count() == 0


def test_generate_code_without_config(relay, dm):
    r = relay.app.test_client(user=dm).post('/ttrpg/relay/generate-code')
    assert r.status_code == 200
    assert r.get_json() == {'ok': False, 'message': 'Set relay URL and secret first.', 'code': None}


def test_generate_code_creates_session_and_pushes(relay, dm):
    _enabled(relay, sid='old-sid', code='OLDCOD')
    relay.settings['relay_push_last_drop'] = 'x|y|z'
    seen = {}

    def create(url, kw):
        seen.update(kw['json'])
        return _Resp({'session_id': kw['json']['session_id'], 'code': kw['json']['code']})
    relay.routes['/session/create'] = create
    r = relay.app.test_client(user=dm).post('/ttrpg/relay/generate-code')
    d = r.get_json()
    assert d['ok'] is True and d['code'] == seen['code'] and len(d['code']) == 6
    assert 'New session created' in d['message']
    assert relay.settings['relay_session_id'] == seen['session_id'] != 'old-sid'
    assert relay.settings['relay_push_last_drop'] == '' and relay.settings['relay_applied_mutation_ids'] == '[]'
    assert relay.pushes == ['chars', 'users', 'feeds', 'library'] and relay.ws_calls == ['restart']


def test_reuse_code_keeps_identity(relay, dm):
    c = relay.app.test_client(user=dm)
    assert c.post('/ttrpg/relay/reuse-code').get_json()['ok'] is False        # nothing to reuse
    _enabled(relay, sid='keep-sid', code='KEEPME')
    relay.routes['/session/create'] = lambda url, kw: _Resp(kw['json'])
    d = c.post('/ttrpg/relay/reuse-code').get_json()
    assert d['ok'] and d['code'] == 'KEEPME' and 'unchanged' in d['message']
    assert relay.settings['relay_session_id'] == 'keep-sid'
    # an older relay minting fresh identity is reported, not hidden
    relay.routes['/session/create'] = lambda url, kw: _Resp({'session_id': 'fresh', 'code': 'FRESH1'})
    d = c.post('/ttrpg/relay/reuse-code').get_json()
    assert d['code'] == 'FRESH1' and 'NEW code' in d['message']


def test_create_response_lost_but_session_exists(relay, dm):
    """A timed-out create is probed with GET /sync and treated as success."""
    _enabled(relay)

    def timeout(url, kw):
        raise TimeoutError('slow relay')
    relay.routes['/session/create'] = timeout
    relay.routes['/sync'] = {'characters': []}
    d = relay.app.test_client(user=dm).post('/ttrpg/relay/generate-code').get_json()
    assert d['ok'] is True and relay.settings['relay_session_code'] == d['code']


def test_create_unreachable(relay, dm):
    _enabled(relay)

    def down(url, kw):
        raise ConnectionError('nope')
    relay.routes['/session/create'] = down
    relay.routes['/sync'] = down
    d = relay.app.test_client(user=dm).post('/ttrpg/relay/generate-code').get_json()
    assert d['ok'] is False and 'Could not reach relay' in d['message']
    assert relay.settings['relay_session_code'] == 'ABC123'


# ── server-to-server (X-Relay-Secret) ─────────────────────────────────────────

@pytest.fixture()
def party_world(relay):
    from models.user import tblUsers
    from models.ttrpg import (tblSessions, tblCharacters, tblSessionParty, tblBattleMaps,
                              tblBattleMapTokens, tblMonsterTemplates, tblSessionMonsters)
    u = tblUsers(username='alice', display_name='Alice', role='player', active=1,
                 created_at='2026-01-01 00:00:00')
    u.set_password('pw')
    db.session.add(u)
    db.session.flush()
    ch = tblCharacters(user_id=u.user_id, name='Hero', char_class='Fighter', race='Elf', level=4,
                       hp_current=22, hp_max=30, ac=16, speed=30, portrait_path='hero.png',
                       active=1, created_at='2026-01-01 00:00:00')
    sess = tblSessions(title='S', status='active', created_at='2026-01-01 00:00:00')
    db.session.add_all([ch, sess])
    db.session.flush()
    db.session.add(tblSessionParty(session_id=sess.session_id, character_id=ch.character_id,
                                   joined_at='2026-01-01 00:00:00'))
    bm = tblBattleMaps(session_id=sess.session_id, name='M', grid_cols=11, grid_rows=6,
                       bg_image='bg.png', is_active=1, created_at='2026-01-01 00:00:00')
    tpl = tblMonsterTemplates(name='Goblin', hp_max=7, ac=13, created_at='2026-01-01 00:00:00')
    db.session.add_all([bm, tpl])
    db.session.flush()
    sm = tblSessionMonsters(session_id=sess.session_id, template_id=tpl.template_id,
                            display_name='Goblin 1', hp_current=5, hp_max=7)
    db.session.add(sm)
    db.session.flush()
    db.session.add_all([
        tblBattleMapTokens(map_id=bm.map_id, entity_type='player', entity_id=ch.character_id,
                           col=5, row=0, updated_at='2026-01-01 00:00:00'),
        tblBattleMapTokens(map_id=bm.map_id, entity_type='monster', entity_id=sm.monster_id,
                           col=10, row=5, updated_at='2026-01-01 00:00:00'),
    ])
    db.session.commit()
    relay.settings.update({'relay_secret': 's3cret', 'relay_session_id': 'sess-1',
                           'relay_session_code': 'ABC123'})
    return types.SimpleNamespace(relay=relay, user=u, char=ch, sess=sess, bm=bm)


def test_auth_verify_requires_the_secret(party_world):
    c = party_world.relay.app.test_client()
    r = c.post('/ttrpg/relay/api/auth/verify', json={'username': 'alice', 'password': 'pw'})
    assert r.status_code == 401 and r.get_json() == {'ok': False, 'error': 'unauthorized'}
    r = c.post('/ttrpg/relay/api/auth/verify', json={'username': 'alice', 'password': 'pw'},
               headers={'X-Relay-Secret': 'wrong'})
    assert r.status_code == 401
    party_world.relay.settings['relay_secret'] = ''       # unset secret never matches
    r = c.post('/ttrpg/relay/api/auth/verify', json={}, headers={'X-Relay-Secret': ''})
    assert r.status_code == 401


def test_auth_verify(party_world):
    c = party_world.relay.app.test_client()
    h = {'X-Relay-Secret': 's3cret'}
    r = c.post('/ttrpg/relay/api/auth/verify', json={'username': 'alice'}, headers=h)
    assert r.status_code == 400 and r.get_json()['error'] == 'missing credentials'
    r = c.post('/ttrpg/relay/api/auth/verify', json={'username': 'alice', 'password': 'bad'}, headers=h)
    assert r.status_code == 401 and r.get_json()['error'] == 'invalid credentials'
    r = c.post('/ttrpg/relay/api/auth/verify', json={'username': ' alice ', 'password': 'pw'}, headers=h)
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] and d['user_id'] == party_world.user.user_id and d['display_name'] == 'Alice'
    assert d['relay_session_id'] == 'sess-1'
    ch = d['character']
    assert ch['name'] == 'Hero' and ch['class'] == 'Fighter' and ch['race'] == 'Elf' and ch['level'] == 4
    assert ch['hp_current'] == 22 and ch['hp_max'] == 30 and ch['ac'] == 16 and ch['speed'] == 30
    assert ch['portrait_url'].startswith('http') and ch['portrait_url'].endswith('/static/uploads/portraits/hero.png')


def test_auth_verify_no_character_in_active_session(party_world):
    party_world.sess.status = 'ended'
    db.session.commit()
    r = party_world.relay.app.test_client().post(
        '/ttrpg/relay/api/auth/verify', json={'username': 'alice', 'password': 'pw'},
        headers={'X-Relay-Secret': 's3cret'})
    assert r.status_code == 200 and r.get_json()['character'] is None


def test_session_info(party_world):
    c = party_world.relay.app.test_client()
    assert c.get('/ttrpg/relay/api/session/info').status_code == 401
    r = c.get('/ttrpg/relay/api/session/info', headers={'X-Relay-Secret': 's3cret'})
    assert r.status_code == 200
    d = r.get_json()
    assert d['relay_session_id'] == 'sess-1' and d['code'] == 'ABC123'
    assert d['sceneplay_session_id'] == party_world.sess.session_id
    m = d['map']
    assert m['grid_cols'] == 11 and m['grid_rows'] == 6 and m['url'].endswith('/static/uploads/battlemaps/bg.png')
    toks = {t['token_type']: t for t in m['tokens']}
    assert toks['player']['label'] == 'Hero' and toks['player']['character_id'] == party_world.char.character_id
    assert toks['player']['x_pct'] == 0.5 and toks['player']['y_pct'] == 0.0
    assert toks['monster']['label'] == 'Goblin 1' and toks['monster']['hp_current'] == 5
    assert toks['monster']['x_pct'] == 1.0 and toks['monster']['y_pct'] == 1.0
    # no active session -> map null
    party_world.sess.status = 'ended'
    db.session.commit()
    d = c.get('/ttrpg/relay/api/session/info', headers={'X-Relay-Secret': 's3cret'}).get_json()
    assert d['sceneplay_session_id'] is None and d['map'] is None

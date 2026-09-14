"""P3 TTRPG core: page-data endpoints, sheet mutations, sessions, users —
JWT roles per the auth matrix."""
import io

from tests.conftest import auth


def _mk_char(client, tok, name='Smoke Hero', **extra):
    body = {'name': name, 'char_class': 'Fighter', 'race': 'Human', 'level': 3, 'hp_max': 30, 'ac': 15, **extra}
    r = client.post('/api/v1/characters', json=body, headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()['character_id']


def test_page_data_requires_login(client):
    for p in ('/api/v1/ttrpg/dashboard', '/api/v1/characters', '/api/v1/characters/new-options', '/api/v1/sessions', '/api/v1/users'):
        assert client.get(p).status_code == 401, p


def test_dashboard_dm_vs_player(client, dm_token, player_token):
    d = client.get('/api/v1/ttrpg/dashboard', headers=auth(dm_token)).json()
    assert set(d) >= {'campaigns', 'sessions', 'characters', 'active_session'}
    assert client.get('/api/v1/ttrpg/dashboard', headers=auth(player_token)).json() == {'redirect': '/ttrpg/my-character'}
    r = client.get('/api/v1/characters?scope=all', headers=auth(player_token))
    assert r.status_code == 403 and r.json()['code'] == 'dm_required'


def test_character_create_page_edit_delete(client, dm_token, player_token):
    cid = _mk_char(client, player_token)
    mine = client.get('/api/v1/characters?scope=mine&all=1', headers=auth(player_token)).json()
    assert any(c['character_id'] == cid for c in mine['characters'])
    page = client.get(f'/api/v1/characters/{cid}/page', headers=auth(player_token)).json()
    assert page['can_edit'] and not page['is_dm'] and page['char']['name'] == 'Smoke Hero'
    assert page['char']['hp_pct'] == 100 and page['char']['stat_keys'] and 'conditions' in page
    for k in ('races_lib', 'classes_lib', 'weapon_props', 'game_systems', 'dcc_sizes', 'subclass_options'):
        assert k in page, k
    # another player cannot see it
    from tests.conftest import _make_user
    from security.jwt import issue_token
    other = issue_token(_make_user('otherplayer', 'player'))
    assert client.get(f'/api/v1/characters/{cid}/page', headers=auth(other)).status_code == 403
    # DM can, and can edit via multipart (portrait optional)
    assert client.get(f'/api/v1/characters/{cid}/page', headers=auth(dm_token)).json()['is_dm']
    r = client.post(f'/api/v1/characters/{cid}', data={'name': 'Smoke Hero II', 'level': '4', 'hp_max': '40', 'hp_current': '35'}, headers=auth(dm_token))
    assert r.status_code == 200
    opts = client.get(f'/api/v1/characters/{cid}/edit-options', headers=auth(dm_token)).json()
    assert opts['char']['name'] == 'Smoke Hero II' and opts['char']['level'] == 4 and opts['char']['hp_current'] == 35
    assert client.post('/api/v1/characters', json={'name': ''}, headers=auth(player_token)).status_code == 400
    r = client.post(f'/ttrpg/character/{cid}/delete', headers=auth(dm_token))
    assert r.status_code == 200 and 'removed' in r.json()['message']


def test_sheet_mutations(client, player_token):
    H = auth(player_token)
    cid = _mk_char(client, player_token, name='Mutant')
    r = client.post(f'/ttrpg/character/{cid}/hp-delta', json={'delta': -7}, headers=H).json()
    assert r['ok'] and r['hp_current'] == 23
    assert client.post(f'/ttrpg/character/{cid}/hp-delta', json={'delta': 99}, headers=H).json()['hp_current'] == 30
    assert client.post(f'/ttrpg/character/{cid}/save-field', json={'field': 'gold', 'value': 12}, headers=H).json()['ok']
    assert client.post(f'/ttrpg/character/{cid}/condition', json={'condition': 'Blinded', 'action': 'add'}, headers=H).json()['ok']
    page = client.get(f'/api/v1/characters/{cid}/page', headers=H).json()
    assert page['char']['gold'] == 12 and page['char']['conditions'] == ['Blinded']
    rid = client.post(f'/ttrpg/character/{cid}/resources', json={'resource_name': 'Ki', 'current_val': 2, 'max_val': 4}, headers=H).json()
    assert rid['ok']
    res = client.get(f'/api/v1/characters/{cid}/page', headers=H).json()['char']['resources']
    assert res and res[0]['resource_name'] == 'Ki'
    assert client.post(f"/ttrpg/resource/{res[0]['resource_id']}/delta", json={'delta': -1}, headers=H).json()['current_val'] == 1
    assert client.delete(f"/ttrpg/resource/{res[0]['resource_id']}", headers=H).json()['ok']
    sk = client.post(f'/ttrpg/character/{cid}/skills', json={'skill_name': 'Stealth', 'bonus': 3, 'proficient': 1}, headers=H).json()
    assert sk['ok']
    roll = client.post('/ttrpg/dice/roll', json={'character_id': cid, 'char_name': 'Mutant', 'count': 1, 'sides': 20, 'modifier': 2, 'label': 'Stealth', 'adv_mode': 'normal'}, headers=H).json()
    assert roll['ok'] and 3 <= roll['total'] <= 22 and roll['expression'].startswith('1d20')
    feed = client.get('/ttrpg/dice/feed', headers=H).json()
    assert feed and feed[0]['roll_id'] == roll['roll_id']
    assert client.get('/ttrpg/dice/system', headers=H).json()['id']


def test_sessions_lifecycle(client, dm_token, player_token):
    H = auth(dm_token)
    cid = _mk_char(client, player_token, name='Party Member')
    opts = client.get('/api/v1/sessions/new-options', headers=H).json()
    assert 'campaigns' in opts and 'game_systems' in opts and opts['today']
    assert client.get('/api/v1/sessions', headers=auth(player_token)).status_code == 403
    r = client.post('/api/v1/sessions', json={'title': 'Smoke Session', 'session_number': 7, 'game_system': 'dnd5e', 'character_ids': [cid]}, headers=H)
    assert r.status_code == 200
    sid = r.json()['session_id']
    page = client.get(f'/api/v1/sessions/{sid}/page', headers=H).json()
    assert page['sess']['title'] == 'Smoke Session' and page['party_ids'] == [cid] and page['party'][0]['name'] == 'Party Member'
    assert set(page) >= {'campaigns', 'game_systems', 'game', 'all_chars', 'monsters', 'campaign_scenes', 'current_vol', 'conditions'}
    assert client.post(f'/ttrpg/sessions/{sid}/edit', json={'title': 'Renamed', 'session_number': 8, 'session_date': '2026-09-14', 'campaign_id': None, 'game_system': 'dnd5e'}, headers=H).json()['title'] == 'Renamed'
    n = client.post(f'/ttrpg/sessions/{sid}/notes/add', json={'title': 'T', 'body': 'B'}, headers=H).json()
    assert n['ok'] and n['note_id']
    assert client.post(f"/ttrpg/sessions/{sid}/notes/{n['note_id']}/update", json={'title': 'T2', 'body': 'B2'}, headers=H).json()['ok']
    notes = client.get(f'/ttrpg/sessions/{sid}/notes/list', headers=H).json()['notes']
    assert [x['title'] for x in notes] == ['T2']
    assert client.get(f'/ttrpg/sessions/{sid}/mapnotes/list', headers=H).json()['ok']
    assert client.post(f"/ttrpg/sessions/{sid}/notes/{n['note_id']}/delete", headers=H).json()['ok']
    assert client.post(f'/ttrpg/sessions/{sid}/status', json={'status': 'active'}, headers=H).json()['ok']
    assert client.get('/api/v1/sessions', headers=H).json()['sessions'][0]['status'] == 'active'
    d = client.get('/api/v1/ttrpg/dashboard', headers=H).json()
    assert d['active_session']['session_id'] == sid
    mine = client.get('/api/v1/characters?scope=mine', headers=auth(player_token)).json()
    assert [c['character_id'] for c in mine['characters']] == [cid]
    assert client.post(f'/ttrpg/sessions/{sid}/party/{cid}/remove', headers=H).json()['ok']
    assert client.get(f'/api/v1/sessions/{sid}/page', headers=H).json()['party_ids'] == []
    assert client.post(f'/ttrpg/sessions/{sid}/delete', headers=H).json()['ok']
    assert client.get(f'/api/v1/sessions/{sid}/page', headers=H).status_code == 404
    client.post(f'/ttrpg/character/{cid}/delete', headers=H)


def test_users_admin(client, dm_token, player_token):
    H = auth(dm_token)
    assert client.get('/api/v1/users', headers=auth(player_token)).status_code == 403
    r = client.post('/api/v1/users', json={'username': 'smokeuser', 'display_name': 'Smoke', 'password': 'pw12345', 'role': 'player'}, headers=H)
    assert r.status_code == 200, r.text
    uid = r.json()['user']['user_id']
    rows = client.get('/api/v1/users', headers=H).json()['users']
    assert any(u['user_id'] == uid and u['role'] == 'player' and 'characters' in u for u in rows)
    assert client.post(f'/api/v1/users/{uid}/edit', json={'username': 'smokeuser2', 'display_name': 'Smoke Two'}, headers=H).json()['ok']
    assert client.post(f'/api/v1/users/{uid}/reset-password', json={'new_password': 'newpw123'}, headers=H).json()['ok']
    assert client.post('/api/v1/auth/login', json={'username': 'smokeuser2', 'password': 'newpw123'}).status_code == 200
    assert client.post(f'/api/v1/users/{uid}/delete', headers=H).json()['ok']
    assert client.post('/api/v1/auth/login', json={'username': 'smokeuser2', 'password': 'newpw123'}).status_code == 401

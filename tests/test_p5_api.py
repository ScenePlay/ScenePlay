"""P5 reference libraries + monsters + handouts: /api/v1 page-data endpoints,
the JSON mutations that replaced form+flash+redirect, sync job plumbing
(offline), and the DM/player auth matrix — over the session client like
tests/test_ttrpg_api.py."""
import pytest

from tests.conftest import auth

LIB_KINDS = ('feats', 'weapons', 'armor', 'spells', 'skills', 'races', 'equipment', 'classes', 'subclasses')


# ── auth matrix ────────────────────────────────────────────────────────────────

def test_page_data_requires_login(client):
    for p in ['/api/v1/reference/library', '/api/v1/reference/settings', '/api/v1/monsters/page',
              '/api/v1/monsters/homebrew/new', '/api/v1/handouts'] + [f'/api/v1/reference/{k}' for k in LIB_KINDS]:
        assert client.get(p).status_code == 401, p


def test_dm_only_pages_and_mutations_reject_players(client, player_token):
    H = auth(player_token)
    for p in ['/api/v1/reference/settings', '/api/v1/monsters/page', '/api/v1/monsters/homebrew/new',
              '/ttrpg/monsters/search?q=a'] + [f'/api/v1/reference/{k}' for k in LIB_KINDS]:
        r = client.get(p, headers=H)
        assert r.status_code == 403 and r.json()['code'] == 'dm_required', p
    for p in ('/ttrpg/reference/feats/add', '/ttrpg/reference/feats/sync', '/ttrpg/reference/sync/run/rules',
              '/ttrpg/reference/libraries/clear', '/ttrpg/reference/library/dcc/restore', '/ttrpg/monsters/sync',
              '/ttrpg/monsters/homebrew/new', '/ttrpg/monsters/instance/1/hp'):
        r = client.post(p, json={'name': 'x'}, headers=H)
        assert r.status_code == 403, p
    # players may read the browse page and the sheet's search/lookup endpoints
    assert client.get('/api/v1/reference/library', headers=H).status_code == 200
    assert client.get('/ttrpg/reference/feats/search?q=', headers=H).status_code == 200
    assert client.get('/ttrpg/reference/lookup/conditions?q=', headers=H).status_code == 200
    assert client.get('/ttrpg/reference/lookup/nope', headers=H).status_code == 404
    assert client.get('/ttrpg/reference/sync/status/feats', headers=H).json()['running'] is False
    assert client.get('/ttrpg/monsters/sync/status', headers=H).json()['running'] is False


# ── reference libraries ────────────────────────────────────────────────────────

def test_library_pages_shape(client, dm_token):
    H = auth(dm_token)
    for k in LIB_KINDS:
        d = client.get(f'/api/v1/reference/{k}', headers=H).json()
        assert d['kind'] == k and d['title'] and isinstance(d['rows'], list) and isinstance(d['total'], int), k
        assert 'q' in d['filters'] and d['api_label'] and d['current_api'] in d['api_options'], k
    assert 'categories' in client.get('/api/v1/reference/equipment', headers=H).json()
    sub = client.get('/api/v1/reference/subclasses', headers=H).json()
    assert 'class_names' in sub and 'feats_by_sub' in sub
    lib = client.get('/api/v1/reference/library', headers=H).json()
    assert [c['key'] for c in lib['categories']][:3] == ['armor', 'features', 'classes']
    assert all({'key', 'label', 'items'} <= set(c) for c in lib['categories'])


def test_feat_add_filter_delete(client, dm_token):
    H = auth(dm_token)
    r = client.post('/ttrpg/reference/feats/add', json={'name': '', 'description': 'x'}, headers=H)
    assert r.status_code == 400 and not r.json()['ok']
    r = client.post('/ttrpg/reference/feats/add', json={'name': 'P5 Test Feat', 'prerequisites': 'STR 13', 'description': 'Hits harder.'}, headers=H).json()
    assert r['ok'] and 'Added custom feat' in r['message']
    fid = r['id']
    d = client.get('/api/v1/reference/feats?q=P5%20Test&src=homebrew', headers=H).json()
    assert [f['feat_lib_id'] for f in d['rows']] == [fid] and d['filters'] == {'q': 'P5 Test', 'src': 'homebrew'}
    assert d['rows'][0]['source'] == 'homebrew' and d['rows'][0]['prerequisites'] == 'STR 13'
    assert client.get('/api/v1/reference/feats?src=srd', headers=H).json()['rows'] == [] or all(f['source'] == 'srd' for f in client.get('/api/v1/reference/feats?src=srd', headers=H).json()['rows'])
    s = client.get('/ttrpg/reference/feats/search?q=p5%20test', headers=H).json()
    assert s and s[0]['feat_lib_id'] == fid and set(s[0]) == {'feat_lib_id', 'name', 'prerequisites', 'description'}
    assert client.post(f'/ttrpg/reference/feats/{fid}/delete', headers=H).json()['message'] == 'Deleted "P5 Test Feat".'
    assert client.post(f'/ttrpg/reference/feats/{fid}/delete', headers=H).status_code == 404


def test_weapon_add_edit_delete_multipart_and_json(client, dm_token):
    H = auth(dm_token)
    r = client.post('/ttrpg/reference/weapons/add', data={'name': 'P5 Blade', 'weapon_category': 'Martial', 'weapon_range': 'Melee',
                                                          'damage_dice': '1d8', 'damage_type': 'Slashing', 'range_normal': '', 'weight': '3.5',
                                                          'properties': 'Finesse, Light', 'image_url': ''}, headers=H).json()
    assert r['ok'] and r['message'] == 'Added "P5 Blade" to the weapons library.'
    wid = r['id']
    row = next(w for w in client.get('/api/v1/reference/weapons?q=P5%20Blade', headers=H).json()['rows'] if w['weapon_lib_id'] == wid)
    assert row['weight'] == 3.5 and row['range_normal'] == 0 and row['source'] == 'homebrew'
    r = client.post(f'/ttrpg/reference/weapons/{wid}/edit', json={'name': 'P5 Blade II', 'damage_dice': '1d10', 'range_normal': 20, 'range_long': 60,
                                                                  'weight': 4, 'image_url': 'https://example.test/x.png'}, headers=H).json()
    assert r['ok'] and r['message'] == 'Updated "P5 Blade II".'
    s = client.get('/ttrpg/reference/weapons/search?q=P5%20Blade', headers=H).json()
    assert s[0]['damage_dice'] == '1d10' and s[0]['range_normal'] == 20
    row = next(w for w in client.get('/api/v1/reference/weapons', headers=H).json()['rows'] if w['weapon_lib_id'] == wid)
    assert row['image_url'] == 'https://example.test/x.png'
    assert client.post(f'/ttrpg/reference/weapons/{wid}/delete', headers=H).json()['ok']
    assert client.post(f'/ttrpg/reference/weapons/{wid}/edit', json={'name': 'x'}, headers=H).status_code == 404


def test_armor_spell_skill_race_class_equipment_flows(client, dm_token):
    H = auth(dm_token)
    a = client.post('/ttrpg/reference/armor/add', data={'name': 'P5 Mail', 'armor_category': 'Heavy', 'armor_class_base': '16', 'max_dex_bonus': '',
                                                        'str_minimum': '13', 'stealth_disadvantage': 'on', 'weight': '55'}, headers=H).json()
    assert a['ok']
    row = client.get('/api/v1/reference/armor?q=P5%20Mail', headers=H).json()['rows'][0]
    assert row['max_dex_bonus'] is None and row['stealth_disadvantage'] == 1 and row['dex_bonus'] == 0
    assert client.post(f"/ttrpg/reference/armor/{a['id']}/edit", json={'name': 'P5 Mail', 'max_dex_bonus': 2, 'dex_bonus': True}, headers=H).json()['ok']
    srch = [x for x in client.get('/ttrpg/reference/armor/search?q=P5%20Mail', headers=H).json() if x['armor_lib_id'] == a['id']]
    assert srch[0]['max_dex_bonus'] == 2 and srch[0]['dex_bonus'] == 1 and srch[0]['game_system'] == 'dnd5e'
    assert client.post(f"/ttrpg/reference/armor/{a['id']}/delete", headers=H).json()['ok']

    sp = client.post('/ttrpg/reference/spells/add', json={'name': 'P5 Bolt', 'level': 3, 'school': 'Evocation', 'description': 'Deals 8d6 fire damage.', 'concentration': 'on'}, headers=H).json()
    assert sp['ok']
    d = client.get('/api/v1/reference/spells?level=3&school=Evocation&src=homebrew', headers=H).json()
    row = next(s for s in d['rows'] if s['spell_lib_id'] == sp['id'])
    assert row['damage_dice'] == '8d6' and row['damage_type'] == 'fire' and row['concentration'] == 1
    assert d['filters']['level'] == '3'
    ss = client.get('/ttrpg/reference/spells/search?q=P5%20Bolt&limit=5', headers=H).json()
    assert ss[0]['spell_lib_id'] == sp['id'] and ss[0]['source'] == 'homebrew'
    assert client.post(f"/ttrpg/reference/spells/{sp['id']}/delete", headers=H).json()['ok']

    sk = client.post('/ttrpg/reference/skills/add', json={'name': 'P5 Lockpicking', 'ability_score': 'DEX', 'game_system': 'dcc', 'description': 'Utility. Opens locks.'}, headers=H).json()
    assert sk['ok']
    d = client.get('/api/v1/reference/skills?system=dcc&q=P5', headers=H).json()
    assert d['system'] == 'dcc' and d['rows'][0]['game_system'] == 'dcc'
    s = client.get('/ttrpg/reference/skills/search?q=P5%20Lock&system=dcc', headers=H).json()
    assert s[0]['category'] == 'Utility'
    assert client.get('/ttrpg/reference/skills/search?q=P5%20Lock&system=dnd5e', headers=H).json() == []
    assert client.post(f"/ttrpg/reference/skills/{sk['id']}/delete", headers=H).json()['ok']

    rc = client.post('/ttrpg/reference/races/add', json={'name': 'P5 Folk', 'speed': 35, 'size': 'Medium', 'traits_text': 'Darkvision\nKeen Senses'}, headers=H).json()
    assert rc['ok']
    s = client.get('/ttrpg/reference/races/search?q=P5%20Folk', headers=H).json()
    assert s[0]['speed'] == 35 and s[0]['game_system'] == 'dnd5e'
    assert client.post(f"/ttrpg/reference/races/{rc['id']}/delete", headers=H).json()['ok']

    cl = client.post('/ttrpg/reference/classes/add', json={'name': 'P5 Hunter', 'hit_die': 10, 'saving_throws': 'STR, DEX', 'subclasses': 'A, B, C, D'}, headers=H).json()
    assert cl['ok']
    s = client.get('/ttrpg/reference/classes/search?q=P5%20Hunter', headers=H).json()
    assert s[0]['hit_die'] == 10 and s[0]['subclasses'] == 'A, B, C, D'
    assert client.post(f"/ttrpg/reference/classes/{cl['id']}/delete", headers=H).json()['ok']

    eq = client.post('/ttrpg/reference/equipment/add', json={'name': 'P5 Rope', 'category': 'Adventuring Gear', 'weight': 10, 'cost': '1 gp'}, headers=H).json()
    assert eq['ok']
    d = client.get('/api/v1/reference/equipment?cat=Adventuring%20Gear', headers=H).json()
    assert 'Adventuring Gear' in d['categories'] and any(i['equipment_lib_id'] == eq['id'] for i in d['rows'])
    assert client.get('/ttrpg/reference/equipment/search?q=P5%20Rope', headers=H).json()[0]['cost'] == '1 gp'
    assert client.post(f"/ttrpg/reference/equipment/{eq['id']}/delete", headers=H).json()['ok']


def test_subclass_with_features(client, dm_token):
    H = auth(dm_token)
    assert client.post('/ttrpg/reference/subclasses/add', json={'name': 'P5 Way', 'class_name': ''}, headers=H).status_code == 400
    r = client.post('/ttrpg/reference/subclasses/add', json={'name': 'P5 Way', 'class_name': 'Monk', 'flavor': 'Monastic Tradition'}, headers=H).json()
    assert r['ok'] and 'P5 Way' in r['message']
    sid = r['id']
    assert client.post('/ttrpg/reference/subclasses/add', json={'name': 'p5 way', 'class_name': 'Monk'}, headers=H).status_code == 400
    f = client.post('/ttrpg/reference/subclasses/features/add', json={'subclass_lib_id': sid, 'name': 'Storm Strike', 'level': 99, 'description': 'Zap.'}, headers=H).json()
    assert f['ok'] and '(level 20)' in f['message']
    d = client.get('/api/v1/reference/subclasses?cls=Monk&src=homebrew', headers=H).json()
    row = next(s for s in d['rows'] if s['subclass_lib_id'] == sid)
    assert row['flavor'] == 'Monastic Tradition'
    assert [x['name'] for x in d['feats_by_sub']['p5 way']] == ['Storm Strike']
    lk = client.get('/ttrpg/reference/lookup/subclasses?q=P5%20Way', headers=H).json()
    assert lk == [{'name': 'P5 Way', 'sub': 'Monk • Monastic Tradition', 'desc': ''}]
    lk = client.get('/ttrpg/reference/lookup/features?q=Storm%20Strike&limit=5', headers=H).json()
    assert lk[0]['sub'] == 'Monk • P5 Way • Level 20'
    r = client.post(f'/ttrpg/reference/subclasses/{sid}/delete', headers=H).json()
    assert r['ok'] and 'and its 1 homebrew features' in r['message']
    assert client.get('/ttrpg/reference/lookup/features?q=Storm%20Strike', headers=H).json() == []
    assert client.post(f"/ttrpg/reference/features/{f['id']}/delete", headers=H).status_code == 404


def test_settings_page_save_test_and_clear(client, dm_token, monkeypatch):
    import routers.reference as ref
    H = auth(dm_token)
    d = client.get('/api/v1/reference/settings', headers=H).json()
    assert d['current'] in d['api_options'] and d['default'] == ref.MERGED_API
    assert [j['job'] for j in d['sync_jobs']][:2] == ['monsters', 'feats'] and len(d['sync_jobs']) == 17
    assert client.post('/api/v1/reference/settings', json={'api_choice': 'custom', 'custom_url': ''}, headers=H).status_code == 400
    r = client.post('/api/v1/reference/settings', json={'api_choice': 'custom', 'custom_url': 'https://example.test/api'}, headers=H).json()
    assert r['ok'] and r['current'] == 'https://example.test/api'
    assert client.get('/api/v1/reference/settings', headers=H).json()['current'] == 'https://example.test/api'
    assert client.get('/api/v1/reference/feats', headers=H).json()['api_label'] == 'Custom'
    r = client.post('/api/v1/reference/settings', json={'api_choice': ref.MERGED_API}, headers=H).json()
    assert r['ok'] and r['message'].startswith('API URL updated to:')

    class _Resp:
        def __init__(self, keys): self._k = keys
        def raise_for_status(self): pass
        def json(self): return {k: 1 for k in self._k}
    monkeypatch.setattr(ref.requests, 'get', lambda url, timeout=None: _Resp(['spells', 'monsters', 'feats']))
    t = client.get('/ttrpg/reference/settings/test?url=https://example.test/api', headers=H).json()
    assert t == {'ok': True, 'endpoints': ['spells', 'monsters', 'feats']}
    t = client.get('/ttrpg/reference/settings/test', headers=H).json()      # merged: both bases
    assert t['ok'] and len(t['endpoints']) == 2 and t['endpoints'][0].startswith('2024 ok')

    fid = client.post('/ttrpg/reference/feats/add', json={'name': 'P5 Keep Me'}, headers=H).json()['id']
    r = client.post('/ttrpg/reference/libraries/clear', json={'scope': 'srd'}, headers=H).json()
    assert r['ok'] and 'homebrew kept' in r['message']
    assert any(f['feat_lib_id'] == fid for f in client.get('/api/v1/reference/feats', headers=H).json()['rows'])
    r = client.post('/ttrpg/reference/libraries/clear', data={'scope': 'homebrew'}, headers=H).json()
    assert r['ok'] and r['cleared'] >= 1 and 'homebrew rows' in r['message']
    assert not any(f['feat_lib_id'] == fid for f in client.get('/api/v1/reference/feats', headers=H).json()['rows'])


def test_dcc_restore_returns_json(client, dm_token):
    r = client.post('/ttrpg/reference/library/dcc/restore', headers=auth(dm_token))
    assert r.status_code == 200 and r.json()['ok'] and 'restored' in r.json() and 'Dungeon Crawler Carl' in r.json()['message']


def test_sync_job_runs_in_thread_and_reports_status(client, dm_token, monkeypatch):
    """Offline: the sync function is stubbed; the trigger returns {job}, the
    poller sees the finished state, a second trigger while running is a 409."""
    import threading
    import routers.reference as ref
    H = auth(dm_token)
    gate = threading.Event()

    def fake_sync(state=None):
        state['total'] = 3
        gate.wait(5)
        state.update({'done': 3, 'added': 2, 'skipped': 1, 'errors': 0})
        return 2, 1, 0
    monkeypatch.setitem(ref.EXTRA_SYNCS, 'rules', fake_sync)
    assert client.post('/ttrpg/reference/sync/run/nope', headers=H).status_code == 404
    r = client.post('/ttrpg/reference/sync/run/rules', headers=H)
    assert r.status_code == 200 and r.json() == {'job': 'rules'}
    assert client.post('/ttrpg/reference/sync/run/rules', headers=H).status_code == 409
    s = client.get('/ttrpg/reference/sync/status/rules', headers=H).json()
    assert s['running'] is True and s['total'] == 3
    gate.set()
    for _ in range(100):
        s = client.get('/ttrpg/reference/sync/status/rules', headers=H).json()
        if not s['running']:
            break
        import time
        time.sleep(0.02)
    assert s['running'] is False and s['message'] == '2 added, 1 skipped, 0 errors.' and s['added'] == 2
    # the event stream carried the job
    import sqlite3
    import core.config as config
    con = sqlite3.connect(config.DB_PATH)
    topics = [t for (t,) in con.execute("SELECT topic FROM tblEvents WHERE topic='syncjob:rules'")]
    con.close()
    assert topics


def test_monster_sync_uses_same_runner(client, dm_token, monkeypatch):
    import routers.monsters as mon
    H = auth(dm_token)
    monkeypatch.setattr(mon, 'sync_monsters_from_api', lambda state=None: (0, 0, 'offline'))
    assert client.post('/ttrpg/monsters/sync', headers=H).json() == {'job': 'monsters'}
    for _ in range(100):
        s = client.get('/ttrpg/monsters/sync/status', headers=H).json()
        if not s['running']:
            break
        import time
        time.sleep(0.02)
    assert s['message'] == '0 added, 0 skipped, offline errors.'


# ── monsters ───────────────────────────────────────────────────────────────────

def _mk_session(client, H, title='P5 Fight'):
    r = client.post('/api/v1/sessions', json={'title': title, 'session_number': 9, 'status': 'planning'}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()['session_id']


def test_monster_library_homebrew_and_session_instances(client, dm_token):
    H = auth(dm_token)
    page = client.get('/api/v1/monsters/page', headers=H).json()
    assert {'synced', 'sessions', 'conditions', 'monster_types', 'api_label', 'api_options'} <= set(page)
    assert 'Blinded' in page['conditions']
    new = client.get('/api/v1/monsters/homebrew/new', headers=H).json()
    assert new['m'] is None and new['stats'] == {} and 'fantasy' in new['icon_genres']
    assert client.post('/ttrpg/monsters/homebrew/new', data={'name': ''}, headers=H).status_code == 400
    r = client.post('/ttrpg/monsters/homebrew/new', data={'name': 'P5 Ogre', 'size': 'Large', 'monster_type': 'giant', 'hp_max': '59', 'ac': '11',
                                                          'str_val': '19', 'dex_val': '8', 'cr': '2', 'xp': '450', 'speed': '40 ft.', 'notes': 'Club attack.'}, headers=H).json()
    assert r['ok'] and r['message'] == 'Homebrew entry "P5 Ogre" created.'
    tid = r['template_id']
    s = client.get('/ttrpg/monsters/search?q=P5%20Ogre&source=homebrew&limit=5', headers=H).json()
    assert s == [{'template_id': tid, 'name': 'P5 Ogre', 'cr': '2', 'type': 'giant', 'size': 'Large', 'hp_max': 59, 'ac': 11, 'source': 'homebrew'}]
    assert client.get('/ttrpg/monsters/search?q=P5%20Ogre&cr_min=5', headers=H).json() == []
    assert client.get('/ttrpg/monsters/search?q=P5%20Ogre&cr_min=1&cr_max=3&type=GIANT', headers=H).json()[0]['template_id'] == tid
    det = client.get(f'/ttrpg/monsters/{tid}/detail', headers=H).json()
    assert det['ok'] and det['stats']['strength'] == 19 and det['stats']['armor_class'] == [{'value': 11, 'type': 'natural'}]
    view = client.get(f'/api/v1/monsters/{tid}/view-page', headers=H).json()
    assert view['m']['name'] == 'P5 Ogre' and view['sm'] is None and view['prof'] == 2 and view['game']['id']
    assert view['stats']['notes'] == 'Club attack.' and view['image_url'] == ''
    ed = client.get(f'/api/v1/monsters/homebrew/{tid}', headers=H).json()
    assert ed['m']['template_id'] == tid and ed['stats']['speed'] == {'walk': '40 ft.'}
    r = client.post(f'/ttrpg/monsters/homebrew/{tid}/edit', json={'name': 'P5 Ogre Chief', 'hp_max': 80, 'ac': 12, 'cr': '5', 'size': 'Large', 'monster_type': 'giant'}, headers=H).json()
    assert r['ok'] and r['message'] == 'Homebrew entry "P5 Ogre Chief" updated.'
    view = client.get(f'/api/v1/monsters/{tid}/view-page', headers=H).json()
    assert view['m']['hp_max'] == 80 and view['prof'] == 3 and view['stats']['notes'] == ''  # form fields overwrite, extras preserved
    assert view['stats']['special_abilities'] == []
    assert client.post(f'/ttrpg/monsters/homebrew/{tid}/image', json={'image_url': '/static/uploads/monsters/nope.png'}, headers=H).status_code == 400

    sid = _mk_session(client, H)
    assert client.post(f'/ttrpg/monsters/{tid}/add-to-session', data={'count': '2'}, headers=H).status_code == 400
    r = client.post(f'/ttrpg/monsters/{tid}/add-to-session', data={'session_id': str(sid), 'count': '2', 'hp_override': '10'}, headers=H).json()
    assert r['ok'] and r['session_title'] == 'P5 Fight' and [c['display_name'] for c in r['created']] == ['P5 Ogre Chief 1', 'P5 Ogre Chief 2']
    mid = r['created'][0]['monster_id']
    sess = client.get(f'/api/v1/sessions/{sid}/page', headers=H).json()
    assert [m['hp_max'] for m in sess['monsters']] == [10, 10]
    view = client.get(f'/api/v1/monsters/{tid}/view-page?instance={mid}', headers=H).json()
    assert view['sm']['monster_id'] == mid and view['sm']['hp_current'] == 10 and view['sm']['session_id'] == sid
    assert client.get(f'/api/v1/monsters/{tid}/view-page?instance=999999', headers=H).json()['sm'] is None
    r = client.post(f'/ttrpg/monsters/instance/{mid}/hp', json={'delta': -4}, headers=H).json()
    assert r == {'ok': True, 'hp_current': 6, 'hp_pct': 60, 'is_alive': 1}
    r = client.post(f'/ttrpg/monsters/instance/{mid}/hp-set', json={'hp': 0}, headers=H).json()
    assert r['hp_current'] == 0 and r['is_alive'] == 0
    assert client.post(f'/ttrpg/monsters/instance/{mid}/revive', headers=H).json()['ok']
    assert client.post(f'/ttrpg/monsters/instance/{mid}/initiative', json={'initiative': 14}, headers=H).json()['initiative'] == 14
    r = client.post(f'/ttrpg/monsters/instance/{mid}/condition', json={'condition': 'Prone', 'action': 'add'}, headers=H).json()
    assert r['conditions'] == ['Prone']
    r = client.post(f'/ttrpg/monsters/instance/{mid}/condition', json={'condition': 'Prone', 'action': 'remove'}, headers=H).json()
    assert r['conditions'] == []
    assert client.post(f'/ttrpg/monsters/instance/{mid}/delete', headers=H).json()['ok']
    assert client.post(f'/ttrpg/monsters/instance/{mid}/delete', headers=H).status_code == 404
    assert len(client.get(f'/api/v1/sessions/{sid}/page', headers=H).json()['monsters']) == 1
    r = client.post(f'/ttrpg/monsters/homebrew/{tid}/delete', headers=H)
    assert r.status_code == 400 and 'still in a session' in r.json()['error']      # instance 2 is still placed
    mid2 = client.get(f'/api/v1/sessions/{sid}/page', headers=H).json()['monsters'][0]['monster_id']
    assert client.post(f'/ttrpg/monsters/instance/{mid2}/delete', headers=H).json()['ok']
    r = client.post(f'/ttrpg/monsters/homebrew/{tid}/delete', headers=H).json()
    assert r['ok'] and r['message'] == '"P5 Ogre Chief" deleted.'
    assert client.get(f'/api/v1/monsters/homebrew/{tid}', headers=H).status_code == 404
    client.post(f'/ttrpg/sessions/{sid}/delete', headers=H)


def test_homebrew_random_and_srd_guards(client, dm_token):
    from core.db import db
    from models.ttrpg import tblMonsterTemplates
    H = auth(dm_token)
    d = client.get('/ttrpg/monsters/homebrew/random?kind=vehicle&genre=fantasy&tier=boss', headers=H).json()
    assert d['name'] and 'hp_max' in d and 'cr' in d
    t = tblMonsterTemplates(api_index='p5-srd-goblin', name='P5 SRD Goblin', cr='1/4', source='srd', stats_json='{}', created_at='t')
    db.session.add(t)
    db.session.commit()
    tid = t.template_id
    try:
        assert client.get(f'/api/v1/monsters/homebrew/{tid}', headers=H).json()['redirect'] == '/ttrpg/monsters'
        assert client.post(f'/ttrpg/monsters/homebrew/{tid}/edit', json={'name': 'x'}, headers=H).status_code == 400
        assert client.post(f'/ttrpg/monsters/homebrew/{tid}/delete', headers=H).status_code == 400
        assert client.get(f'/api/v1/monsters/{tid}/view-page', headers=H).json()['prof'] == 2
    finally:
        db.session.expire_all()
        db.session.delete(db.session.get(tblMonsterTemplates, tid))
        db.session.commit()


@pytest.mark.parametrize('kind', LIB_KINDS)
def test_library_page_deep_link_filters_echo(client, dm_token, kind):
    d = client.get(f'/api/v1/reference/{kind}?q=zzz-nothing', headers=auth(dm_token)).json()
    assert d['rows'] == [] and d['filters']['q'] == 'zzz-nothing'

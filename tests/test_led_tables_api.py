"""Grid.js server protocol (list/search/sort/add/update/delete) on the P8
tables — scenePattern, wledPattern, ledconfig, serverIP, cronSchedule — plus
their side endpoints (LED registry, effect/palette feeds, the Test buttons,
the LAN-scan status, the cron wizard and the Apply button). Integrations and
crontab writes are off under test (conftest), so Test/Apply never leave the box."""
import json

from core.db import db
from tests.conftest import auth


def _h(tok):
    return auth(tok)


# ── scenePattern (RPiLED) ───────────────────────────────────────────────────────

def test_led_registry_feed(client, dm_token):
    reg = client.get('/api/led/patterns', headers=_h(dm_token)).json()
    assert 'schema' in reg and reg['patterns']
    first = reg['patterns'][0]
    assert {'type', 'name', 'desc', 'params'} <= set(first)
    assert any(p['type'] == 'solid' for p in reg['patterns'])


def test_scene_pattern_crud_and_grid_protocol(client, dm_token):
    H = _h(dm_token)
    client.post('/api/scenesaddrow', json={'campaign_id': 1}, headers=H)
    sid = client.get('/api/scenes?sort=-scene_ID').json()['data'][0]['scene_ID']
    client.post('/api/scenes', json={'scene_ID': sid, 'sceneName': 'Glowing Cavern'}, headers=H)

    r = client.post('/api/scenepatternaddrow', json={}, headers=H)
    assert r.status_code == 200 and 'new row' in r.text
    rows = client.get('/api/scenePattern?sort=-scenePattern_ID', headers=H).json()['data']
    pk = rows[0]['scenePattern_ID']
    assert rows[0]['scene_ID'] == 0 and rows[0]['patternType'] == 'solid'
    assert isinstance(rows[0]['params'], dict) and rows[0]['name']

    # scene + order + pattern type (params reset to that pattern's defaults)
    assert client.post('/api/scenePattern', json={'scenePattern_ID': pk, 'scene_ID': sid, 'orderBy': 3}, headers=H).status_code == 204
    assert client.post('/api/scenePattern', json={'scenePattern_ID': pk, 'patternType': 'nope'}, headers=H).status_code == 400
    reg = client.get('/api/led/patterns', headers=H).json()
    other = next(p['type'] for p in reg['patterns'] if p['type'] != 'solid')
    assert client.post('/api/scenePattern', json={'scenePattern_ID': pk, 'patternType': other}, headers=H).status_code == 204
    d = client.get('/api/scenePattern?search=Glowing', headers=H).json()
    assert d['total'] == 1 and d['data'][0]['patternType'] == other and d['data'][0]['orderBy'] == 3
    # params are coerced against the type (clamped, unknown keys dropped)
    assert client.post('/api/scenePattern', json={'scenePattern_ID': pk, 'params': {'brightness': 99, 'bogus': 1}}, headers=H).status_code == 204
    p = client.get('/api/scenePattern?search=Glowing', headers=H).json()['data'][0]['params']
    assert 'bogus' not in p and p['brightness'] <= 1
    assert client.get('/api/scenePattern?sort=-orderBy&start=0&length=1', headers=H).status_code == 200
    assert client.post('/api/scenePattern', json={'orderBy': 1}, headers=H).status_code == 400
    assert client.post('/api/scenePattern', json={'scenePattern_ID': 999999, 'orderBy': 1}, headers=H).status_code == 404

    r = client.post('/api/scenepatterndelrow', json={'scenePattern_ID': pk}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.get('/api/scenePattern?search=Glowing', headers=H).json()['total'] == 0
    client.post('/api/scenesdelrow', json={'scene_ID': sid}, headers=H)


def test_rpi_led_test_builds_payload(client, dm_token, monkeypatch):
    import core.config as config
    import routers.tables.scene_pattern as sp
    H = _h(dm_token)
    client.post('/api/scenepatternaddrow', json={}, headers=H)
    pk = client.get('/api/scenePattern?sort=-scenePattern_ID', headers=H).json()['data'][0]['scenePattern_ID']
    sent = []
    monkeypatch.setattr(sp, 'dispatch_led', lambda payload, local=True: sent.append(payload))
    monkeypatch.setattr(config, 'INTEGRATIONS', True)
    assert client.post('/api/RPiLEDTest', json={'scenePattern_ID': pk}, headers=H).status_code == 204
    assert len(sent) == 1 and json.loads(sent[0])['patterns'][0]['type'] == 'solid'
    # unsaved preview values
    assert client.post('/api/RPiLEDTest', json={'scenePattern_ID': pk, 'patternType': 'solid', 'params': {'color': [1, 2, 3]}}, headers=H).status_code == 204
    assert json.loads(sent[1])['patterns'][0]['color'] == [1, 2, 3]
    assert client.post('/api/RPiLEDTest', json={'scenePattern_ID': pk, 'patternType': 'nope'}, headers=H).status_code == 400
    assert client.post('/api/RPiLEDTest', json={'scenePattern_ID': 999999}, headers=H).status_code == 404
    # SP_INTEGRATIONS=0: 204 but nothing leaves the box
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    assert client.post('/api/RPiLEDTest', json={'scenePattern_ID': pk}, headers=H).status_code == 204
    assert len(sent) == 2
    client.post('/api/scenepatterndelrow', json={'scenePattern_ID': pk}, headers=H)


# ── wledPattern ─────────────────────────────────────────────────────────────────

def test_wled_lookup_feeds(client, dm_token):
    H = _h(dm_token)
    assert 'data' in client.get('/api/effects', headers=H).json()
    assert 'data' in client.get('/api/pallettes', headers=H).json()


def test_wled_pattern_crud_and_grid_protocol(client, dm_token, monkeypatch):
    H = _h(dm_token)
    client.post('/api/scenesaddrow', json={'campaign_id': 1}, headers=H)
    sid = client.get('/api/scenes?sort=-scene_ID').json()['data'][0]['scene_ID']
    client.post('/api/scenes', json={'scene_ID': sid, 'sceneName': 'Neon Bar'}, headers=H)

    r = client.post('/api/wledpatternaddrow', json={'scene_ID': sid}, headers=H)
    assert r.status_code == 200 and 'new row' in r.text
    row = client.get('/api/wledPattern?sort=-wledPattern_ID', headers=H).json()['data'][0]
    pk = row['wledPattern_ID']
    assert row['scene_ID'] == sid and row['color1'] == '[0,0,0]' and row['speed'] == 125
    assert client.post('/api/wledPattern', json={'wledPattern_ID': pk, 'color2': '[10,20,30]', 'brightness': 200, 'effect': 5}, headers=H).status_code == 204
    d = client.get('/api/wledPattern?search=Neon', headers=H).json()
    assert d['total'] == 1 and d['data'][0]['color2'] == '[10,20,30]' and d['data'][0]['brightness'] == 200
    assert client.get('/api/wledPattern?sort=-orderBy,+scene_ID&start=0&length=5', headers=H).status_code == 200
    assert client.post('/api/wledPattern', json={'speed': 1}, headers=H).status_code == 400
    assert client.post('/api/wledPattern', json={'wledPattern_ID': 999999, 'speed': 1}, headers=H).status_code == 404

    # Test button: one setWledEffect per matching row, gated by SP_INTEGRATIONS
    import core.config as config
    import routers.tables.wled_pattern as wl
    calls = []
    monkeypatch.setattr(wl, 'setWledEffect', lambda *a: calls.append(a))
    monkeypatch.setattr(config, 'INTEGRATIONS', True)
    assert client.post('/api/WLEDTest', json={'wledPattern_ID': pk}, headers=H).status_code == 204
    assert len(calls) == 1 and calls[0][0] == 5 and calls[0][3] == '[10,20,30]'
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    assert client.post('/api/WLEDTest', json={'wledPattern_ID': pk}, headers=H).status_code == 204
    assert len(calls) == 1
    assert client.post('/api/WLEDTest', json={}, headers=H).status_code == 400

    r = client.post('/api/wledpatterndelrow', json={'wledPattern_ID': pk}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.post('/api/wledpatterndelrow', json={'wledPattern_ID': pk}, headers=H).status_code == 404
    client.post('/api/scenesdelrow', json={'scene_ID': sid}, headers=H)


# ── ledconfig ───────────────────────────────────────────────────────────────────

def test_led_config_grid_protocol(client, dm_token):
    from models.ledConfig import tblledconfig
    H = _h(dm_token)
    row = tblledconfig(pin=21, ledCount=77, brightness=0.5, active=0)
    db.session.add(row)
    db.session.commit()
    pk = row.ledConfig_ID
    d = client.get('/api/ledconfig', headers=H).json()
    assert d['total'] >= 1 and any(r['ledConfig_ID'] == pk for r in d['data'])
    assert client.get('/api/ledconfig?search=77', headers=H).json()['total'] == 1
    assert client.get('/api/ledconfig?sort=-pin&start=0&length=1', headers=H).json()['data'][0]['pin'] >= 21
    assert client.post('/api/ledconfigsave', json={'ledConfig_ID': pk, 'ledCount': 88, 'brightness': 0.25, 'active': 1}, headers=H).status_code == 204
    m = client.get('/api/ledconfigmodel', headers=H).json()['data']
    mine = next(r for r in m if r['ledConfig_ID'] == pk)
    assert mine['ledCount'] == 88 and mine['brightness'] == 0.25 and mine['active'] == 1
    assert client.post('/api/ledconfigsave', json={'ledCount': 1}, headers=H).status_code == 400
    assert client.post('/api/ledconfigsave', json={'ledConfig_ID': 999999, 'ledCount': 1}, headers=H).status_code == 404
    r = client.post('/api/ledconfigdelrow', json={'ledConfig_ID': pk}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.post('/api/ledconfigdelrow', json={'ledConfig_ID': pk}, headers=H).status_code == 404


# ── serverIP + LAN scan ─────────────────────────────────────────────────────────

def test_server_ip_crud_and_grid_protocol(client, dm_token):
    H = _h(dm_token)
    r = client.post('/api/serveripaddrow', headers=H)
    assert r.status_code == 200 and 'new row' in r.text
    row = client.get('/api/serverIP?sort=-ServerIP_ID', headers=H).json()['data'][0]
    pk = row['ServerIP_ID']
    assert row['ipAddress'] == '127.0.0.1' and row['active'] == 1 and row['serverroleid'] == 1
    assert client.post('/api/serverIP', json={'ServerIP_ID': pk, 'serverName': 'Kitchen Pi', 'ipAddress': '10.9.8.7', 'serverroleid': 2, 'active': 0}, headers=H).status_code == 204
    d = client.get('/api/serverIP?search=Kitchen', headers=H).json()
    assert d['total'] == 1 and d['data'][0]['ipAddress'] == '10.9.8.7' and d['data'][0]['serverroleid'] == 2
    assert client.get('/api/serverIP?search=10.9.8', headers=H).json()['total'] == 1
    assert client.get('/api/serverIP?sort=-serverName,+ipAddress&start=0&length=2', headers=H).status_code == 200
    assert client.post('/api/serverIP', json={'serverName': 'x'}, headers=H).status_code == 400
    assert client.post('/api/serverIP', json={'ServerIP_ID': 999999, 'serverName': 'x'}, headers=H).status_code == 404
    r = client.post('/api/serveripdelrow', json={'ServerIP_ID': pk}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.get('/api/serverIP?search=Kitchen', headers=H).json()['total'] == 0


def test_ping_network_start_status_and_netscan_topic(client, dm_token, monkeypatch):
    import integrations.discovery as discovery
    import core.events as events
    import routers.tables.server_ip as sip
    H = _h(dm_token)
    seen = {}
    progress = {'state': 'done', 'done': 3, 'total': 3,
                'summary': {'local_ip': '10.0.0.2', 'hosts_open': 1, 'sceneplay': 1, 'wled': 0, 'obs': 0, 'created': 1, 'updated': 0}}
    monkeypatch.setattr(discovery, 'start_scan', lambda app: (seen.__setitem__('app', app), True)[1])
    monkeypatch.setattr(discovery, 'get_progress', lambda: dict(progress))
    emitted = []
    monkeypatch.setattr(events, 'emit', lambda topic, payload=None: emitted.append((topic, payload)))
    monkeypatch.setattr(sip, '_watching', False)
    assert client.post('/api/pingnetwork', headers=H).json() == {'started': True}
    # discovery gets the Flask-app stand-in (needs .app_context())
    assert hasattr(seen['app'], 'app_context')
    assert client.get('/api/pingnetwork/status', headers=H).json()['state'] == 'done'
    # the watcher thread pushes the final state on the netscan topic
    import time
    for _ in range(50):
        if emitted:
            break
        time.sleep(0.02)
    assert emitted and emitted[0][0] == 'netscan' and emitted[0][1]['state'] == 'done'


# ── cronSchedule + wizard ───────────────────────────────────────────────────────

def test_cron_schedule_crud_and_grid_protocol(client, dm_token):
    H = _h(dm_token)
    r = client.post('/api/cronscheduleaddrow', headers=H)
    assert r.status_code == 200
    pk = r.json()['schedule_id']
    row = next(x for x in client.get('/api/cronSchedule', headers=H).json()['data'] if x['schedule_id'] == pk)
    assert row['name'] == 'New Schedule' and row['minute'] == '*' and row['active'] == 0
    assert client.post('/api/cronSchedule', json={'schedule_id': pk, 'name': 'Nightly lights', 'minute': '30', 'hour': '22', 'command': 'echo hi', 'active': 1}, headers=H).status_code == 204
    d = client.get('/api/cronSchedule?search=Nightly', headers=H).json()
    assert d['total'] == 1 and d['data'][0]['hour'] == '22' and d['data'][0]['active'] == 1
    assert client.get('/api/cronSchedule?search=echo', headers=H).json()['total'] == 1
    assert client.get('/api/cronSchedule?search=Nightly&sort=-name&start=0&length=1', headers=H).json()['data'][0]['name'] == 'Nightly lights'
    assert client.post('/api/cronSchedule', json={'name': 'x'}, headers=H).status_code == 400
    assert client.post('/api/cronSchedule', json={'schedule_id': 999999, 'name': 'x'}, headers=H).status_code == 404
    # Apply: SP_CRON_APPLY=0 under test -> counts the active rows, writes nothing
    a = client.post('/api/applycronschedules', headers=H).json()
    assert a['success'] is True and a['count'] >= 1 and a['dry_run'] is True
    r = client.post('/api/cronscheduledelrow', json={'schedule_id': pk}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.post('/api/cronscheduledelrow', json={'schedule_id': pk}, headers=H).status_code == 404


def test_cron_wizard_saves_row_with_generated_command(client, dm_token, monkeypatch):
    import core.config as config
    H = _h(dm_token)
    monkeypatch.setattr(config, 'PORT', 8086)
    client.post('/api/scenesaddrow', json={'campaign_id': 1}, headers=H)
    sid = client.get('/api/scenes?sort=-scene_ID').json()['data'][0]['scene_ID']
    client.post('/api/scenes', json={'scene_ID': sid, 'sceneName': 'Dawn Chorus'}, headers=H)

    r = client.post('/api/cronwizard', json={'action': 'scene', 'scene_id': sid, 'time': '06:30', 'days': [1, 2, 3, 4, 5]}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res['success'] is True and res['dry_run'] is True
    assert res['description'] == "on weekdays at 6:30 AM: activate scene 'Dawn Chorus'"
    row = next(x for x in client.get('/api/cronSchedule', headers=H).json()['data'] if x['schedule_id'] == res['schedule_id'])
    assert row['active'] == 1 and (row['minute'], row['hour'], row['day_of_week']) == ('30', '6', '1-5')
    assert f'http://localhost:8086/activatescenes/?id={sid}' in row['command']
    assert row['name'] == row['description'][:60]

    r = client.post('/api/cronwizard', json={'action': 'volume', 'volume': 40, 'time': '23:05', 'days': [0, 6], 'name': 'Quiet'}, headers=H)
    assert r.status_code == 200 and r.json()['description'] == 'on weekends at 11:05 PM: set volume to 40%'
    pk2 = r.json()['schedule_id']

    assert client.post('/api/cronwizard', json={'action': 'scene', 'scene_id': sid, 'time': '25:00', 'days': [1]}, headers=H).status_code == 400
    assert client.post('/api/cronwizard', json={'action': 'allstop', 'time': '10:00', 'days': []}, headers=H).json()['error'] == 'Pick at least one day.'
    assert client.post('/api/cronwizard', json={'action': 'mystery', 'time': '10:00', 'days': [1]}, headers=H).status_code == 400
    assert client.post('/api/cronwizard', json={'action': 'scene', 'scene_id': 0, 'time': '10:00', 'days': [1]}, headers=H).json()['error'] == 'Pick a scene.'

    for pk in (res['schedule_id'], pk2):
        client.post('/api/cronscheduledelrow', json={'schedule_id': pk}, headers=H)
    client.post('/api/scenesdelrow', json={'scene_ID': sid}, headers=H)


def test_p8_tables_are_dm_gated_when_locked(client, dm_token):
    from sql import appsettingSet
    appsettingSet('DMOnlyScenePlay', '1')
    try:
        assert client.get('/api/serverIP').status_code == 403
        assert client.get('/api/led/patterns').status_code == 403
        assert client.post('/api/cronscheduleaddrow').status_code == 403
        assert client.get('/api/serverIP', headers=_h(dm_token)).status_code == 200
    finally:
        appsettingSet('DMOnlyScenePlay', '0')

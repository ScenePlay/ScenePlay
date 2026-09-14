"""Grid.js server protocol on the ScenePlay tables + the global filters +
home/utilities page data (P1 routers)."""
from tests.conftest import auth


def _h(tok):
    return auth(tok)


def test_scene_crud_and_grid_protocol(client, dm_token):
    H = _h(dm_token)
    r = client.post('/api/scenesaddrow', json={'campaign_id': 1}, headers=H)
    assert r.status_code == 200 and 'new row' in r.text
    sid = client.get('/api/scenes').json()['data'][-1]['scene_ID']
    assert client.post('/api/scenes', json={'scene_ID': sid, 'sceneName': 'Zebra Tavern', 'orderBy': 5}, headers=H).status_code == 204
    d = client.get('/api/scenes?search=Zebra').json()
    assert d['total'] == 1 and d['data'][0]['sceneName'] == 'Zebra Tavern'
    assert set(d['data'][0]) >= {'scene_ID', 'sceneName', 'active', 'orderBy', 'campaign_id', 'queued', 'rule'}
    assert client.get('/api/scenes?sort=-sceneName&start=0&length=1').json()['data'][0]['sceneName'] == 'Zebra Tavern'
    assert client.post('/api/scenes', json={'sceneName': 'x'}, headers=H).status_code == 400
    r = client.post('/api/scenesdelrow', json={'scene_ID': sid}, headers=H)
    assert r.status_code == 200 and 'deleted' in r.text
    assert client.get('/api/scenes?search=Zebra').json()['total'] == 0


def test_scene_edits_are_gated_reads_are_open(client, dm_token):
    from sql import appsettingSet
    appsettingSet('DMOnlyScenePlay', '1')
    try:
        assert client.get('/api/scenes').status_code == 200
        assert client.post('/api/scenesaddrow', json={}).status_code == 403
        assert client.post('/api/scenesaddrow', json={'campaign_id': 0}, headers=_h(dm_token)).status_code == 200
    finally:
        appsettingSet('DMOnlyScenePlay', '0')


def test_campaigns_crud(client, dm_token):
    H = _h(dm_token)
    assert client.post('/api/campaignaddrow', headers=H).status_code == 200
    cid = client.get('/api/campaigns?sort=-campaign_id').json()['data'][0]['campaign_id']
    assert client.post('/api/campaigns', json={'campaign_id': cid, 'campaign_name': 'Strahd'}, headers=H).status_code == 204
    assert client.get('/api/campaigns?search=Strahd').json()['total'] == 1
    assert client.post('/api/campaignSelect', json={'campaign_id': cid}, headers=H).status_code == 204
    assert client.get('/api/getcampaignSelect').json() == {'CampaignID': cid}
    assert client.post('/api/campaigndelrow', json={'campaign_id': cid}, headers=H).status_code == 200
    assert client.post('/api/campaigndelrow', json={'campaign_id': cid}, headers=H).status_code == 404


def test_filters_and_link_tables(client, dm_token):
    H = _h(dm_token)
    client.post('/api/scenesaddrow', json={'campaign_id': 1}, headers=H)
    sid = client.get('/api/scenes?sort=-scene_ID').json()['data'][0]['scene_ID']
    client.post('/api/scenes', json={'scene_ID': sid, 'sceneName': 'Filtered'}, headers=H)
    f = client.post('/api/campaignFilter', json={'campaign_id': 1}, headers=H).json()
    assert f['campaign_id'] == 1 and any(s[0] == sid for s in f['scenes'])
    f2 = client.post('/api/sceneFilter', json={'scene_id': sid}, headers=H).json()
    assert f2['campaign_id'] == 1
    filt = client.get('/api/v1/filters', headers=H).json()
    assert filt['sceneFilter'] == sid and filt['campaignFilter'] == 1
    # link tables default the new row to the scene filter
    assert client.post('/api/musicSceneaddrow', json={}, headers=H).status_code == 200
    rows = client.get('/api/musicScene', headers=H).json()['data']
    assert rows and rows[-1]['scene_ID'] == sid
    ms_id = rows[-1]['musicScene_ID']
    assert client.post('/api/musicScene', json={'musicScene_ID': ms_id, 'volume': 55}, headers=H).status_code == 204
    assert client.post('/api/musicScenedelrow', json={'musicScene_ID': ms_id}, headers=H).status_code == 200
    assert client.post('/api/videoSceneaddrow', json={'scene_ID': sid}, headers=H).status_code == 200
    vs = client.get('/api/videoScene', headers=H).json()['data'][-1]
    assert client.post('/api/videoScenedelrow', json={'videoScene_ID': vs['videoScene_ID']}, headers=H).status_code == 200
    client.post('/api/campaignFilter', json={'campaign_id': 0}, headers=H)
    client.post('/api/scenesdelrow', json={'scene_ID': sid}, headers=H)


def test_media_tables(client, dm_token):
    H = _h(dm_token)
    assert client.post('/api/musicaddrow', json={'scene_ID': 0}, headers=H).status_code == 200
    d = client.get('/api/music?sort=-song_ID', headers=H).json()
    row = d['data'][0]
    assert {'duration', 'uploader', 'artist', 'thumbnail'} <= set(row)
    pk = row['song_ID']
    assert client.post('/api/music', json={'song_ID': pk, 'displayName': 'Song A', 'artist': 'Band'}, headers=H).status_code == 204
    assert client.get('/api/music?search=Song%20A', headers=H).json()['total'] == 1
    assert client.get('/api/music?sort=+duration', headers=H).status_code == 200
    r = client.post('/api/musicdelrow', json={'song_ID': pk}, headers=H)
    assert r.status_code == 200 and r.json()['deleted'] == pk
    assert client.post('/api/videomediaaddrow', json={'scene_ID': 0}, headers=H).status_code == 200
    v = client.get('/api/videomedia?sort=-video_ID', headers=H).json()['data'][0]
    assert client.post('/api/videomediadelrow', json={'video_ID': v['video_ID']}, headers=H).status_code == 200


def test_lookup_feeds(client, dm_token):
    H = _h(dm_token)
    assert 'data' in client.get('/api/genre', headers=H).json()
    st = client.get('/api/dnLoadStatus', headers=H).json()['data']
    assert [s['status_ID'] for s in st][:4] == [1, 2, 3, 4]
    assert 'data' in client.get('/api/serverrole', headers=H).json()


def test_home_and_player_payloads(client, dm_token):
    H = _h(dm_token)
    h = client.get('/api/v1/home', headers=H).json()
    assert set(h) == {'campaigns', 'campaign_selected', 'scenes', 'volume', 'stats'}
    p = client.get('/api/v1/player', headers=H).json()
    assert set(p) == {'volume', 'keep_music', 'nowplaying', 'counts'}
    assert {'songQCnt', 'videoQCnt', 'scene_states'} <= set(p['counts'])


def test_utilities_page_and_settings(client, dm_token, player_token):
    H = _h(dm_token)
    u = client.get('/api/v1/utilities', headers=H).json()
    assert u['is_dm'] is True and u['scenes'][0] == [0, 'None']
    assert client.post('/api/v1/utilities/settings', json={'dm_only_sceneplay': True}, headers=_h(player_token)).status_code == 403
    r = client.post('/api/v1/utilities/settings', json={'media_search_roots': '/nonexistent/x'}, headers=H).json()
    assert 'not found' in r['message']
    r = client.post('/api/v1/utilities/settings', json={'lights_off_on_scene_end': True}, headers=H).json()
    assert 'turn off' in r['message']
    client.post('/api/v1/utilities/settings', json={'lights_off_on_scene_end': False}, headers=H)


def test_backup_roundtrip_via_api(client, dm_token):
    H = _h(dm_token)
    r = client.post('/api/v1/backup/run', headers=H).json()
    name = r['name']
    u = client.get('/api/v1/utilities', headers=H).json()
    b = next(x for x in u['backups'] if x['name'] == name)
    assert client.get(b['url']).status_code == 200            # signed URL, no bearer
    assert client.get('/backups/' + name).status_code == 403   # bare path needs DM
    assert client.get('/backups/' + name, headers=H).status_code == 200
    assert client.post('/api/backupdelete', json={'name': name}, headers=H).json() == {'deleted': name}
    assert client.post('/api/backupdelete', json={'name': '../x.zip'}, headers=H).status_code == 400


def test_downloads_and_chimes(client, dm_token):
    H = _h(dm_token)
    d = client.get('/api/downloads/status', headers=H).json()
    assert d['ok'] and set(d['stats']) == {'music', 'video'}
    assert client.post('/api/downloads/retry', json={'media_type': 'bogus', 'id': 1}, headers=H).status_code == 400
    c = client.get('/api/chimes', headers=H).json()
    assert c['ok'] and c['events']
    assert client.post('/api/chimes', json={'key': 'nope'}, headers=H).status_code == 400


def test_youtube_import_enqueues(client, dm_token, monkeypatch):
    import routers.public as pub
    calls = []
    monkeypatch.setattr(pub, 'enqueue_single', lambda *a: calls.append(a) or 1)
    r = client.post('/api/v1/youtube/import', json={'url': 'https://youtu.be/abc', 'mediaType': 'mp4', 'scene_ID': 0},
                    headers=_h(dm_token))
    assert r.status_code == 200 and calls and calls[0][1] == 'mp4'
    assert client.post('/api/v1/youtube/import', json={'url': ''}, headers=_h(dm_token)).status_code == 400

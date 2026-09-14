"""The runtime 'DM-only ScenePlay' switch: off = LAN-open; on = 403 JSON for
gated media endpoints except the documented session-less carve-outs."""
import pytest

from tests.conftest import auth

OPEN_ALWAYS = [
    ('GET', '/api/server-info'), ('GET', '/api/nowplaying'), ('GET', '/api/songandvideocount'),
    ('GET', '/isAlive'), ('GET', '/api/keepmusicplaying/on'), ('GET', '/api/keepmusicplaying/off'),
    ('POST', '/api/keepmusicplaying'), ('GET', '/api/v1/auth/bootstrap'), ('GET', '/api/v1/health'),
    ('OPTIONS', '/receive_led_patterns'),
]
GATED = [('GET', '/api/v1/player')]


@pytest.fixture()
def dm_only(client):
    from sql import appsettingSet
    appsettingSet('DMOnlyScenePlay', '1')
    yield
    appsettingSet('DMOnlyScenePlay', '0')


@pytest.mark.parametrize('method,path', OPEN_ALWAYS)
def test_open_endpoints_stay_open_under_switch(client, dm_only, method, path):
    r = client.request(method, path)
    assert r.status_code in (200, 204), (path, r.status_code, r.text[:200])


@pytest.mark.parametrize('method,path', GATED)
def test_gated_endpoints_403_for_anon_and_player(client, dm_only, player_token, method, path):
    r = client.request(method, path)
    assert r.status_code == 403 and r.json()['code'] == 'sceneplay_locked'
    r = client.request(method, path, headers=auth(player_token))
    assert r.status_code == 403 and r.json()['code'] == 'sceneplay_locked'


@pytest.mark.parametrize('method,path', GATED)
def test_gated_endpoints_open_for_dm(client, dm_only, dm_token, method, path):
    assert client.request(method, path, headers=auth(dm_token)).status_code == 200


@pytest.mark.parametrize('method,path', GATED)
def test_gated_endpoints_open_when_switch_off(client, method, path):
    assert client.request(method, path).status_code == 200


def test_bootstrap_reports_lock(client, dm_only, player_token, dm_token):
    assert client.get('/api/v1/auth/bootstrap').json()['sceneplay_locked'] is True
    assert client.get('/api/v1/auth/bootstrap', headers=auth(player_token)).json()['sceneplay_locked'] is True
    assert client.get('/api/v1/auth/bootstrap', headers=auth(dm_token)).json()['sceneplay_locked'] is False


def test_events_media_topics_gated(client, dm_only, player_token):
    r = client.get('/api/v1/events?topics=nowplaying', headers=auth(player_token))
    assert r.status_code == 403

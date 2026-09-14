"""External-consumer contracts that must survive the port verbatim (P0 subset:
cron, browser extensions, other boxes, watchdog, forked players). Each row:
method, path, expected auth class."""
import os

import pytest

from tests.conftest import auth


def test_server_info_shape(client):
    d = client.get('/api/server-info').json()
    assert d['app'] == 'ScenePlay'
    assert set(d) == {'app', 'server_name', 'version', 'os', 'machine', 'cores', 'capabilities'}
    assert set(d['capabilities']) == {'led', 'relay'}


def test_is_alive_reports_this_process(client):
    d = client.get('/isAlive').json()
    assert d['isAlive'] == 'true' and d['pid'] == os.getpid() and 'WatchManage' in d


def test_keepmusic_get_toggles(client):
    assert client.get('/api/keepmusicplaying/on').json() == {'keep_music': 1}
    assert client.get('/api/keepmusicplaying/off').json() == {'keep_music': 0}
    r = client.post('/api/keepmusicplaying').json()
    assert r == {'keep_music': 1}
    client.get('/api/keepmusicplaying/off')


def test_receive_led_patterns_preflight_and_validation(client):
    r = client.options('/receive_led_patterns')
    assert r.status_code == 204
    assert r.headers['access-control-allow-private-network'] == 'true'
    assert 'POST' in r.headers['access-control-allow-methods']
    r = client.post('/receive_led_patterns', json={'nope': 1})
    assert r.status_code == 400 and 'patterns' in r.json()['error']
    r = client.post('/receive_led_patterns', json={'patterns': []})
    assert r.status_code == 200 and 'received' in r.json()['message']


def test_cors_header_for_extension(client):
    r = client.get('/api/server-info', headers={'Origin': 'chrome-extension://abc'})
    assert r.headers.get('access-control-allow-origin') == '*'


def test_xpi_mimetype():
    import mimetypes
    import app  # noqa: F401
    assert mimetypes.guess_type('x.xpi')[0] == 'application/x-xpinstall'


def test_chrome_extension_add_video_enqueues(client, monkeypatch):
    import routers.public as pub
    calls = []
    monkeypatch.setattr(pub, 'enqueue_single', lambda *a: calls.append(a) or 1)
    r = client.post('/api/ChromeExtensionAddVideo',
                    json={'url': 'https://youtu.be/abc123', 'flname': '', 'mediaType': 'mp3', 'scene_ID': 1})
    assert r.status_code == 200 and r.json() == 'Success'
    assert calls and calls[0][1] == 'mp3'


def test_mediameta_validation(client):
    assert client.get('/api/mediameta/bogus/1').status_code == 400
    assert client.get('/api/mediameta/music/999999').json() is None


def test_open_paths_do_not_404(client):
    for m, p in [('GET', '/api/nowplaying'), ('GET', '/api/songandvideocount'), ('GET', '/favicon.ico'),
                 ('GET', '/api/v1/health')]:
        assert client.request(m, p).status_code == 200, p


@pytest.mark.parametrize('path', ['/api/v1/events', '/api/v1/users'])
def test_api_paths_need_auth(client, path):
    assert client.get(path).status_code == 401

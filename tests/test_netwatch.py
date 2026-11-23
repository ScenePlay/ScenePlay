"""Wi-Fi fallback hotspot: nmcli parsing, the daemon's mode switching
(ops/netwatch.py), its socket, and the /api/v1/network router."""
import os
import tempfile

import pytest

from ops import netctl, netwatch
from tests.conftest import auth


# ── nmcli parsing ──
def test_split_terse_handles_escaped_colons():
    assert netctl.split_terse(r'*:Cafe\:Guest:72:WPA2') == ['*', 'Cafe:Guest', '72', 'WPA2']
    assert netctl.split_terse(r'a\\b:c') == ['a\\b', 'c']


def test_parse_scan_dedupes_sorts_and_drops_hidden():
    text = '\n'.join([
        ' :Home:40:WPA2',
        ' :Home:81:WPA2',
        ' ::90:WPA2',                 # hidden
        '*:Cafe\\:Guest:55:--',
        ' :Attic:55:WPA3',
    ])
    nets = netctl.parse_scan(text)
    assert [n['ssid'] for n in nets] == ['Home', 'Attic', 'Cafe:Guest']
    assert nets[0]['signal'] == 81
    cafe = nets[2]
    assert cafe['security'] == '' and cafe['in_use'] is True


def test_parse_devices():
    rows = netctl.parse_devices('wlan0:wifi:connected:ScenePlay-Hotspot\neth0:ethernet:unavailable:\n')
    assert rows[0] == {'device': 'wlan0', 'type': 'wifi', 'state': 'connected', 'connection': 'ScenePlay-Hotspot'}
    assert rows[1]['connection'] == ''


def test_key_mgmt_and_errors():
    assert netctl.key_mgmt_for('WPA2', '') is None
    assert netctl.key_mgmt_for('WPA2', 'password1') == 'wpa-psk'
    assert netctl.key_mgmt_for('WPA3', 'password1') == 'sae'
    assert netctl.key_mgmt_for('WPA2 WPA3', 'password1') == 'wpa-psk'
    assert 'Wrong password' in netctl.friendly_error(
        'Error: Connection activation failed: Secrets were required, but not provided.')
    assert 'not found' in netctl.friendly_error('Error: No network with SSID "x" found.')


class Runner:
    """Scripted nmcli: answers by matching argv prefixes, records calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(argv[1:])
        for key, resp in self.answers:
            if all(k in argv for k in key):
                return resp
        return 0, '', ''


def _saved_runner(extra, profiles='Home:802-11-wireless\n'):
    return Runner(extra + [
        (('-t', '-f', 'NAME,TYPE'), (0, profiles, '')),
        (('-g', '802-11-wireless.ssid'), (0, 'Home\n', '')),
    ])


def test_connect_new_profile_failure_deletes_it():
    r = Runner([
        (('-t', '-f', 'NAME,TYPE'), (0, '', '')),
        (('connection', 'up'), (4, '', 'Error: Connection activation failed: Secrets were required')),
    ])
    ok, msg = netctl.Nmcli(runner=r).connect('wlan0', 'Cafe', 'password1', security='WPA2')
    assert not ok and 'Wrong password' in msg
    assert ['connection', 'delete', 'Cafe'] in r.calls
    add = next(c for c in r.calls if c[:2] == ['connection', 'add'])
    assert add[add.index('wifi-sec.psk') + 1] == 'password1'


def test_connect_existing_profile_failure_restores_old_secret():
    r = _saved_runner([
        (('-s', '-g'), (0, 'wpa-psk\noldsecret\n', '')),
        (('connection', 'up'), (4, '', 'Secrets were required')),
    ])
    ok, _ = netctl.Nmcli(runner=r).connect('wlan0', 'Home', 'newsecret1', security='WPA2')
    assert not ok
    mods = [c for c in r.calls if c[:2] == ['connection', 'modify']]
    assert mods[0][-1] == 'newsecret1' and mods[-1][-1] == 'oldsecret'
    assert not any(c[:2] == ['connection', 'delete'] for c in r.calls)   # never deletes a saved network


def test_forget_refuses_hotspot_and_unknown():
    r = _saved_runner([])
    nm = netctl.Nmcli(runner=r)
    assert nm.forget(netctl.HOTSPOT_NAME) is False
    assert nm.forget('Nope') is False
    assert nm.forget('Home') is True
    assert ['connection', 'delete', 'Home'] in r.calls


# ── daemon state machine ──
class FakeNm:
    def __init__(self):
        self.dev = 'wlan0'
        self.eth = None
        self.wifi = None
        self.ap = None              # (ssid, password) while up
        self.stations = 0
        self.saved = [{'name': 'Home', 'ssid': 'Home'}]
        self.visible = [{'ssid': 'Home', 'signal': 70, 'security': 'WPA2', 'in_use': False}]
        self.connect_result = (True, 'Connected')
        self.up_ok = True
        self.calls = []

    def wifi_device(self): return self.dev
    def hwaddr(self, dev): return 'B8:27:EB:12:AB:CD'
    def ip(self, dev): return '192.168.1.50' if self.wifi else None
    def state(self, dev): return {'ethernet': self.eth, 'wifi': self.wifi, 'hotspot': self.ap is not None}
    def scan(self, dev, rescan=True):
        self.calls.append('scan')
        return [] if self.ap else list(self.visible)
    def saved_wifi(self): return list(self.saved)
    def station_count(self, dev): return self.stations
    def forget(self, name): return name == 'Home'

    def hotspot_up(self, dev, ssid, password=None):
        self.calls.append(('ap_up', ssid, password))
        self.ap, self.wifi = (ssid, password), None
        return True, ''

    def hotspot_down(self):
        self.calls.append('ap_down')
        self.ap = None
        return True

    def up(self, name, dev, wait=40):
        self.calls.append(('up', name))
        if self.up_ok:
            self.wifi = name
        return self.up_ok, ''

    def connect(self, dev, ssid, password='', hidden=False, security=''):
        self.calls.append(('connect', ssid, password, security))
        ok, msg = self.connect_result
        if ok:
            self.wifi = ssid
        return ok, msg


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


@pytest.fixture()
def rig(tmp_path):
    nm, clock = FakeNm(), Clock()
    path = str(tmp_path / 'network.json')
    w = netwatch.NetWatch(nm, path, clock=clock, sleep=lambda s: None,
                          boot_grace=75, lost_grace=45, retry_every=300)
    return w, nm, clock, path


def _ap_ups(nm):
    return [c for c in nm.calls if isinstance(c, tuple) and c[0] == 'ap_up']


def test_hotspot_waits_out_the_boot_grace(rig):
    w, nm, clock, _ = rig
    w.tick()
    assert w.mode == 'starting' and nm.ap is None
    clock.t += 74
    w.tick()
    assert nm.ap is None
    clock.t += 2
    w.tick()
    assert w.mode == 'hotspot'
    assert nm.ap == ('ScenePlay-ABCD', None)          # open, named after the MAC
    assert w.scan_cache and w.scan_cache[0]['ssid'] == 'Home'   # scanned BEFORE the AP took the radio


def test_connected_box_never_raises_the_hotspot(rig):
    w, nm, clock, _ = rig
    nm.wifi = 'Home'
    for _ in range(5):
        clock.t += 100
        w.tick()
    assert w.mode == 'client' and nm.ap is None


def test_status_reports_ssid_behind_the_profile_name(rig):
    w, nm, _, _ = rig
    nm.saved = [{'name': 'preconfigured', 'ssid': 'Home'}]
    nm.wifi = 'preconfigured'
    w.tick()
    st = w.status()
    assert st['wifi'] == 'preconfigured' and st['wifi_ssid'] == 'Home'


def test_lost_network_raises_hotspot_after_lost_grace(rig):
    w, nm, clock, _ = rig
    nm.wifi = 'Home'
    clock.t += 200
    w.tick()
    nm.wifi = None
    w.tick()
    assert w.mode == 'waiting'
    clock.t += 46
    w.tick()
    assert w.mode == 'hotspot'


def test_fallback_disabled_stays_offline(rig):
    w, nm, clock, path = rig
    netwatch.save_settings({'fallback_enabled': False}, path)
    clock.t += 500
    w.tick()
    w.tick()
    assert w.mode == 'offline' and nm.ap is None


def test_hotspot_steps_down_only_when_nobody_is_on_it(rig):
    w, nm, clock, _ = rig
    clock.t += 200
    w.tick()
    assert w.mode == 'hotspot'
    nm.stations = 1
    clock.t += 301
    w.tick()
    assert 'ap_down' not in nm.calls                  # a phone is mid-setup: leave it alone
    nm.stations = 0
    w.tick()
    assert ('up', 'Home') in nm.calls
    assert w.mode == 'client' and nm.ap is None


def test_retry_with_no_saved_network_in_range_comes_back_up(rig):
    w, nm, clock, _ = rig
    nm.visible = []
    clock.t += 200
    w.tick()
    clock.t += 301
    w.tick()
    assert 'ap_down' in nm.calls and w.mode == 'hotspot' and nm.ap is not None
    assert len(_ap_ups(nm)) == 2


def test_ethernet_takes_the_fallback_hotspot_down(rig):
    w, nm, clock, _ = rig
    clock.t += 200
    w.tick()
    nm.eth = 'Wired connection 1'
    w.tick()
    assert nm.ap is None
    w.tick()
    assert w.mode == 'client'


def test_play_mode_password_changes_and_exit(rig):
    w, nm, clock, path = rig
    nm.wifi = 'Home'
    netwatch.save_settings({'play_mode': True, 'play_password': ''}, path)
    w.tick()
    assert w.mode == 'play' and nm.ap == ('ScenePlay-ABCD', None)
    assert w.status()['hotspot_open'] is True
    w.tick()
    assert len(_ap_ups(nm)) == 1                     # stable: not re-raised every tick
    netwatch.save_settings({'play_mode': True, 'play_password': 'dungeon42'}, path)
    w.tick()
    assert nm.ap == ('ScenePlay-ABCD', 'dungeon42')
    assert w.status()['hotspot_open'] is False
    nm.stations = 0
    clock.t += 10_000
    w.tick()
    assert w.mode == 'play' and nm.ap is not None   # play mode never steps down by itself
    netwatch.save_settings({'play_mode': False}, path)
    w.tick()
    assert nm.ap is None and w.mode == 'waiting'


def test_connect_from_hotspot_success(rig):
    w, nm, clock, _ = rig
    clock.t += 200
    w.tick()
    assert w.handle({'cmd': 'connect', 'ssid': 'Home', 'password': 'password1'})['ok']
    w.tick()
    assert ('connect', 'Home', 'password1', 'WPA2') in nm.calls   # security from the fresh scan
    assert w.mode == 'client' and nm.ap is None
    assert w.last_attempt['ok'] is True and w.last_attempt['ip'] == '192.168.1.50'


def test_connect_from_hotspot_failure_goes_straight_back(rig):
    w, nm, clock, _ = rig
    clock.t += 200
    w.tick()
    nm.connect_result = (False, 'Wrong password (the network rejected it).')
    w.handle({'cmd': 'connect', 'ssid': 'Home', 'password': 'badpass12'})
    w.tick()
    assert w.mode == 'hotspot' and nm.ap is not None
    st = w.status()
    assert st['last_attempt']['ok'] is False and 'Wrong password' in st['last_attempt']['error']


def test_connect_validation(rig):
    w, *_ = rig
    assert not w.handle({'cmd': 'connect', 'ssid': ''})['ok']
    assert not w.handle({'cmd': 'connect', 'ssid': 'x' * 33})['ok']
    assert not w.handle({'cmd': 'connect', 'ssid': 'Home', 'password': 'short'})['ok']
    assert w.jobs.empty()


def test_scan_command_does_not_scan_while_ap_is_up(rig):
    w, nm, clock, _ = rig
    clock.t += 200
    w.tick()
    nm.calls.clear()
    r = w.handle({'cmd': 'scan'})
    assert r['networks'][0]['ssid'] == 'Home' and 'scan' not in nm.calls


def test_settings_file_defaults_and_mode(tmp_path):
    path = str(tmp_path / 'n.json')
    assert netwatch.load_settings(path) == netwatch.DEFAULTS
    netwatch.save_settings({'fallback_enabled': False, 'play_mode': True, 'play_password': 'abcdefgh'}, path)
    assert netwatch.load_settings(path)['play_password'] == 'abcdefgh'
    if os.name != 'nt':
        assert oct(os.stat(path).st_mode & 0o777) == '0o600'


@pytest.mark.skipif(os.name == 'nt', reason='unix socket')
def test_socket_roundtrip():
    nm = FakeNm()
    nm.wifi = 'Home'
    w = netwatch.NetWatch(nm, os.path.join(tempfile.mkdtemp(), 'n.json'), sleep=lambda s: None)
    w.tick()
    path = os.path.join(tempfile.mkdtemp(), 'nw.sock')
    srv = netwatch.serve(w, path=path)
    try:
        r = netwatch.request('status', path=path)
        assert r['ok'] and r['status']['mode'] == 'client' and r['status']['wifi'] == 'Home'
        assert netwatch.request('nope', path=path)['ok'] is False
    finally:
        srv.shutdown()
        srv.server_close()
    assert netwatch.request('status', path=os.path.join(tempfile.mkdtemp(), 'missing.sock')) is None


# ── router ──
@pytest.fixture()
def daemon(monkeypatch):
    """Fake daemon behind routers.network._ask; .status is what it reports."""
    import routers.network as net

    class D:
        status = {'available': True, 'mode': 'client', 'wifi': 'Home', 'hotspot_ssid': 'ScenePlay-ABCD'}
        sent = []

    def ask(cmd, timeout=5, **kw):
        D.sent.append((cmd, kw))
        if cmd == 'status':
            return {'ok': True, 'status': dict(D.status)}
        if cmd == 'scan':
            return {'ok': True, 'networks': [{'ssid': 'Home', 'signal': 70, 'security': 'WPA2'}], 'age': 3}
        if cmd == 'saved':
            return {'ok': True, 'saved': [{'name': 'Home', 'ssid': 'Home'}]}
        return {'ok': True}

    D.sent = []
    monkeypatch.setattr(net, '_ask', ask)
    monkeypatch.setattr(net, '_writes_allowed', lambda: True)
    return D


def test_status_without_daemon_is_unavailable(client):
    r = client.get('/api/v1/network/status')
    assert r.status_code == 200
    j = r.json()
    assert j['available'] is False and j['setup_open'] is False


def test_scan_and_connect_open_only_in_fallback_hotspot(client, daemon):
    assert client.get('/api/v1/network/scan').status_code == 401
    assert client.post('/api/v1/network/connect', json={'ssid': 'Home'}).status_code == 401
    daemon.status = {**daemon.status, 'mode': 'play'}
    assert client.get('/api/v1/network/scan').status_code == 401      # play-mode guests can't re-point the box
    daemon.status = {**daemon.status, 'mode': 'hotspot'}
    assert client.get('/api/v1/network/status').json()['setup_open'] is True
    assert client.get('/api/v1/network/scan').json()['networks'][0]['ssid'] == 'Home'
    r = client.post('/api/v1/network/connect', json={'ssid': 'Home', 'password': 'password1'})
    assert r.status_code == 200
    assert ('connect', {'ssid': 'Home', 'password': 'password1', 'hidden': False, 'security': ''}) in daemon.sent


def test_scan_for_dm_and_player(client, daemon, dm_token, player_token):
    assert client.get('/api/v1/network/scan', headers=auth(dm_token)).status_code == 200
    assert client.get('/api/v1/network/scan', headers=auth(player_token)).status_code == 403


def test_writes_refused_on_dev_instances(client, daemon, dm_token, monkeypatch):
    import routers.network as net
    monkeypatch.setattr(net, '_writes_allowed', lambda: False)
    r = client.post('/api/v1/network/connect', json={'ssid': 'Home'}, headers=auth(dm_token))
    assert r.status_code == 409 and r.json()['code'] == 'network_disabled'
    assert client.post('/api/v1/network/settings', json={'play_mode': True},
                       headers=auth(dm_token)).status_code == 409


def test_saved_forget_settings_are_dm_only(client, daemon, player_token):
    for method, path in (('GET', '/api/v1/network/saved'), ('POST', '/api/v1/network/forget'),
                         ('GET', '/api/v1/network/settings'), ('POST', '/api/v1/network/settings')):
        assert client.request(method, path).status_code == 401
        assert client.request(method, path, headers=auth(player_token)).status_code == 403


def test_settings_roundtrip_never_returns_the_password(client, daemon, dm_token):
    h = auth(dm_token)
    try:
        r = client.post('/api/v1/network/settings', json={'play_password': 'short'}, headers=h)
        assert r.status_code == 400
        r = client.post('/api/v1/network/settings', json={'play_mode': True, 'play_password': 'dungeon42'}, headers=h)
        assert r.json() == {'fallback_enabled': True, 'play_mode': True, 'has_play_password': True}
        g = client.get('/api/v1/network/settings', headers=h).json()
        assert 'dungeon42' not in str(g) and g['has_play_password'] is True
        assert netwatch.load_settings()['play_password'] == 'dungeon42'
        assert ('reload', {}) in daemon.sent
    finally:
        client.post('/api/v1/network/settings', json={'play_mode': False, 'play_password': ''}, headers=h)


def test_setup_page_served(client):
    r = client.get('/setup/wifi')
    assert r.status_code == 200 and 'ScenePlay Wi-Fi Setup' in r.text

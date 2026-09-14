"""mpv_ipc: the JSON IPC client and the fire-and-forget text contract, against
a fake mpv listening on a unix socket (Linux-only transport in CI; the named
pipe branch is the same protocol)."""
import json
import os
import socket
import threading
import time

import pytest

import media.mpv_ipc as mpv_ipc

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='unix-socket fake mpv')


class FakeMpv:
    """Speaks just enough of mpv's JSON IPC: echoes commands, answers
    get_property from a dict, records everything, can push events."""

    def __init__(self, path):
        self.path = path
        self.props = {'volume': 100, 'pause': False, 'time-pos': 12.5}
        self.commands = []
        self.clients = []
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(path)
        self._srv.listen(2)
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            self.clients.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        buf = b''
        while not self._stop:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                msg = json.loads(line)
                cmd = msg['command']
                self.commands.append(cmd)
                reply = {'error': 'success'}
                if cmd[0] == 'get_property':
                    if cmd[1] in self.props:
                        reply['data'] = self.props[cmd[1]]
                    else:
                        reply['error'] = 'property not found'
                elif cmd[0] == 'set_property':
                    self.props[cmd[1]] = cmd[2]
                elif cmd[0] == 'observe_property':
                    conn.sendall((json.dumps({'event': 'property-change', 'id': cmd[1], 'name': cmd[2],
                                              'data': self.props.get(cmd[2])}) + '\n').encode())
                elif cmd[0] == 'boom':
                    reply['error'] = 'invalid parameter'
                if 'request_id' in msg:
                    reply['request_id'] = msg['request_id']
                    conn.sendall((json.dumps(reply) + '\n').encode())

    def push_event(self, event):
        for c in self.clients:
            try:
                c.sendall((json.dumps(event) + '\n').encode())
            except OSError:
                pass

    def close(self):
        self._stop = True
        self._srv.close()
        for c in self.clients:
            try:
                c.close()
            except OSError:
                pass


@pytest.fixture
def fake(tmp_path, monkeypatch):
    import core.config as config
    prefix = str(tmp_path / 'mpvsocket-')
    monkeypatch.setattr(config, 'MPV_SOCKET_PREFIX', prefix)
    srv = FakeMpv(prefix + 'music')
    yield srv
    srv.close()


def test_text_command_translation():
    assert mpv_ipc._parse_text_command('seek 10') == ['seek', 10]
    assert mpv_ipc._parse_text_command('add volume -10') == ['add', 'volume', -10]
    assert mpv_ipc._parse_text_command('cycle pause') == ['cycle', 'pause']
    assert mpv_ipc._parse_text_command('seek -2.5') == ['seek', -2.5]


def test_mpv_command_writes_json_and_is_silent_when_dead(fake, monkeypatch):
    assert mpv_ipc.mpv_command('music', 'seek 10') is True
    time.sleep(0.2)
    assert ['seek', 10] in fake.commands
    assert mpv_ipc.mpv_command('video', 'cycle pause') is False   # nothing listens there — no exception


def test_client_request_reply_and_errors(fake):
    c = mpv_ipc.MpvClient('music').connect(timeout=2)
    try:
        assert c.connected
        assert c.get('volume') == 100
        c.set('volume', 40)
        assert c.get('volume') == 40
        assert c.get('nope', default='dflt') == 'dflt'
        with pytest.raises(mpv_ipc.MpvError):
            c.command('boom')
        assert ['set_property', 'volume', 40] in fake.commands
    finally:
        c.close()
    assert not c.connected


def test_client_events_and_observers(fake):
    c = mpv_ipc.MpvClient('music').connect(timeout=2)
    seen, ends = [], []
    try:
        c.observe('time-pos', lambda name, val: seen.append((name, val)))
        c.on_event('end-file', ends.append)
        fake.push_event({'event': 'end-file', 'reason': 'eof'})
        fake.push_event({'event': 'property-change', 'id': 1, 'name': 'time-pos', 'data': 20.0})
        deadline = time.time() + 2
        while time.time() < deadline and (len(seen) < 2 or not ends):
            time.sleep(0.02)
        assert ends and ends[0]['reason'] == 'eof'
        assert seen[0] == ('time-pos', 12.5) and ('time-pos', 20.0) in seen
    finally:
        c.close()


def test_connect_times_out_without_a_player(tmp_path, monkeypatch):
    import core.config as config
    monkeypatch.setattr(config, 'MPV_SOCKET_PREFIX', str(tmp_path / 'none-'))
    with pytest.raises(mpv_ipc.MpvError):
        mpv_ipc.MpvClient('music').connect(timeout=0.3)


def test_client_survives_peer_closing(fake):
    c = mpv_ipc.MpvClient('music').connect(timeout=2)
    fake.close()
    time.sleep(0.3)
    with pytest.raises(mpv_ipc.MpvError):
        c.command('get_property', 'volume', timeout=0.5)
    c.close()

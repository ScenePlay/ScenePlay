"""player_ipc.MusicPlayer: the persistent-mpv supervisor driven by a fake
client and a fake spawn, on the scratch DB (raw tables + a queued song)."""
import time

import pytest

import sql
import media.player_ipc as player_ipc
from media.mpv_ipc import MpvError


class FakeProc:
    def __init__(self, pid=4321):
        self.pid = pid
        self.rc = None

    @property
    def returncode(self):
        return self.rc

    def poll(self):
        return self.rc

    def terminate(self):
        self.rc = -15

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        self.rc = -9


class FakeClient:
    def __init__(self):
        self.connected = True
        self.props = {}
        self.calls = []
        self.handlers = {}

    def on_event(self, name, cb):
        self.handlers.setdefault(name, []).append(cb)

    def set(self, prop, value):
        self.calls.append(('set', prop, value))
        self.props[prop] = value

    def command(self, *args, timeout=None):
        self.calls.append(('cmd',) + args)
        if args[0] == 'loadfile' and 'missing' in str(args[1]):
            raise MpvError('file not found')
        return None

    def end(self, reason='eof'):
        for cb in self.handlers.get('end-file', []):
            cb({'event': 'end-file', 'reason': reason})

    def close(self):
        self.connected = False


@pytest.fixture
def env(app, monkeypatch):
    """Scratch DB with the raw tables, one campaign/scene, two queued songs."""
    import sqlite3
    conn = sqlite3.connect(sql.database)
    c = conn.cursor()
    for name, val in (('playsongswitch', '0'), ('playsongPID', '0'), ('currentsong', '0'), ('CurrentScene', '1'),
                      ('KeepMusicPlaying', '0'), ('currentvideo', '0'), ('playvideoswitch', '0')):
        c.execute("DELETE FROM tblAppSettings WHERE name=?", (name,))
        c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES(?,?,?)", (name, val, 'int'))
    c.execute("INSERT INTO tblMusic(song_ID, path, song, pTimes, active, que, dnLoadStatus) VALUES (1, '/tmp/', 'one.mp3', 0, 1, 1, 3)")
    c.execute("INSERT INTO tblMusic(song_ID, path, song, pTimes, active, que, dnLoadStatus) VALUES (2, '/tmp/', 'two.mp3', 0, 1, 1, 3)")
    c.execute("INSERT INTO tblMusicScene(scene_ID, song_ID, volume, loops, orderBy) VALUES (1, 1, 55, 2, 1)")
    c.execute("INSERT INTO tblMusicScene(scene_ID, song_ID, volume, loops, orderBy) VALUES (1, 2, 80, 0, 2)")
    conn.commit()
    conn.close()
    relay_calls = []

    class Relay:
        def output_device(self):
            return None

        def __getattr__(self, name):
            return lambda *a, **k: relay_calls.append(name)
    monkeypatch.setattr(player_ipc, '_relay_audio', Relay())
    monkeypatch.setattr(player_ipc._scene_end, 'notify_if_scene_ended', lambda *a, **k: relay_calls.append('scene_end'))
    emitted = []
    monkeypatch.setattr(player_ipc, '_emit_nowplaying', lambda: emitted.append(1))
    client = FakeClient()
    proc = FakeProc()
    player = player_ipc.MusicPlayer(spawn=lambda dev: proc, client_factory=lambda: client, sleep=lambda s: None)
    return {'player': player, 'client': client, 'proc': proc, 'relay': relay_calls, 'emitted': emitted}


def _setting(name):
    return sql.appsettingFlagGet(name)


def test_idle_until_switch_then_loads_in_scene_order(env):
    p, c = env['player'], env['client']
    assert p.step() is False or p.playing is None
    assert int(_setting('playsongPID')) == 4321                      # persistent mpv's pid stored once
    sql.appsettingAudioPlayFlagUpdate(1)
    assert p.step() is True
    assert p.playing[0] == 1 and int(_setting('currentsong')) == 1
    assert ('set', 'volume', 55) in c.calls and ('set', 'loop-file', 2) in c.calls
    assert ('cmd', 'loadfile', '/tmp/one.mp3', 'replace') in c.calls
    assert 'on_track_start' in env['relay'] and env['emitted']


def test_end_file_advances_and_books_the_play(env):
    p, c = env['player'], env['client']
    sql.appsettingAudioPlayFlagUpdate(1)
    p.step()
    c.end('eof')
    p.step()                                   # finish #1, start #2
    assert p.playing[0] == 2 and int(_setting('currentsong')) == 2
    row = sql.conn_row = None
    import sqlite3
    conn = sqlite3.connect(sql.database)
    row = conn.execute("SELECT pTimes, que FROM tblMusic WHERE song_ID=1").fetchone()
    conn.close()
    assert row == (1, 0)                       # counted, dropped from the queue
    assert ('set', 'loop-file', 'no') in c.calls and ('set', 'volume', 80) in c.calls
    assert 'on_track_end' in env['relay']


def test_drain_turns_the_switch_off_and_notifies(env):
    p, c = env['player'], env['client']
    sql.appsettingAudioPlayFlagUpdate(1)
    p.step(); c.end(); p.step(); c.end(); p.step()     # both tracks played, queue empty
    assert p.playing is None
    assert _setting('playsongswitch') in ('0', 0) and int(_setting('currentsong')) == 0
    assert 'on_playback_stopped' in env['relay'] and 'scene_end' in env['relay']


def test_stop_from_the_transport_is_a_skip_when_queue_has_more(env):
    p, c = env['player'], env['client']
    sql.appsettingAudioPlayFlagUpdate(1)
    p.step()
    c.end('stop')                              # what mpv_ipc.music_stop() causes
    p.step()
    assert p.playing[0] == 2


def test_loadfile_failure_moves_on(env):
    import sqlite3
    conn = sqlite3.connect(sql.database)
    conn.execute("UPDATE tblMusic SET song='missing.mp3' WHERE song_ID=1")
    conn.commit(); conn.close()
    p, c = env['player'], env['client']
    sql.appsettingAudioPlayFlagUpdate(1)
    p.step()
    assert p.playing is None and int(_setting('currentsong')) == 0
    p.step()
    assert p.playing[0] == 2                   # the bad row was counted and skipped


def test_crash_respawns_and_finishes_the_track(env):
    p, c, proc = env['player'], env['client'], env['proc']
    sql.appsettingAudioPlayFlagUpdate(1)
    p.step()
    proc.rc = 1                                # mpv died mid-track
    p.step()
    assert 'on_track_end' in env['relay']
    assert p.proc is proc and p.client is c    # fake spawn hands back the same objects; PID re-stored
    assert int(_setting('playsongPID')) == 4321


def test_mpv_args_and_socket():
    args = player_ipc.mpv_args('/tmp/x-music', 'pulse/sink')
    assert '--idle=yes' in args and '--no-video' in args and '--input-ipc-server=/tmp/x-music' in args
    assert '--audio-device=pulse/sink' in args and any(a.startswith('--af=lavfi=[afade') for a in args)
    assert player_ipc.mpv_args('/tmp/x-music')[-1] == '--keep-open=no'


def test_sql_stop_routes_by_engine(monkeypatch):
    import core.config as config
    calls = []
    monkeypatch.setattr(config, 'PLAYER', 'ipc')
    monkeypatch.setattr(sql.mpv_ipc, 'music_stop', lambda: calls.append('stop'))
    monkeypatch.setattr(sql.os, 'system', lambda cmd: calls.append(cmd))
    sql.queue_next()
    assert calls == ['stop']
    calls.clear()
    monkeypatch.setattr(config, 'PLAYER', 'classic')
    monkeypatch.setattr(sql.mpv_ipc, 'music_fade_out', lambda: calls.append('fade'))
    sql.queue_next()
    assert calls[0] == 'fade' and any('mpvsocket-music' in str(x) for x in calls[1:])


def test_boot_picks_the_engine(monkeypatch):
    import core.config as config
    import core.boot as boot
    monkeypatch.setattr(config, 'PLAYER', 'ipc')
    import inspect
    src = inspect.getsource(boot.start_workers)
    assert 'from media.player_ipc import threader' in src and 'from media.player import threader' in src
    time.sleep(0)


def test_default_engine_is_ipc(monkeypatch):
    import importlib
    import core.config as config
    monkeypatch.delenv('SP_PLAYER', raising=False)
    importlib.reload(config)
    assert config.PLAYER == 'ipc'
    monkeypatch.setenv('SP_PLAYER', 'bogus')
    importlib.reload(config)
    assert config.PLAYER == 'ipc'
    monkeypatch.setenv('SP_PLAYER', 'classic')
    importlib.reload(config)
    assert config.PLAYER == 'classic'
    monkeypatch.delenv('SP_PLAYER', raising=False)
    importlib.reload(config)

"""Persistent music player (SP_PLAYER=ipc).

One mpv process per player for the life of the worker, started idle and fed
tracks with `loadfile` over its JSON IPC (mpv_ipc.MpvClient). Track ends are
mpv `end-file` events, not a 1 s poll on a dead PID; skips and kills are
`stop` commands from the transport routes (mpv_ipc.music_stop), never pkill.

Everything the rest of the app relies on is unchanged: the DB queue and
`select_play_threadQ`, the tblAppSettings switches (`playsongswitch`,
`playsongPID`, `currentsong`), per-scene volume/loops, `update_data_entry`
bookkeeping, the relay audio hooks (on_track_start/end, output_device), and
scene_end. `playsongPID` now holds the persistent mpv's PID, so the relay's
per-process capture attaches once and stays attached.

The worker still runs in the forked player process (boot.start_workers
picks `threader` from here when SP_PLAYER=ipc) and still exits when its
parent dies, like the classic player.
"""
import logging
import os
import signal
import subprocess
import threading
import time

import core.config as config
from media.mpv_ipc import MpvClient, MpvError, socket_path
from core.procutil import pid_alive
from sql import (appsettingAudioPlayFlag, appsettingAudioPlayFlagUpdate, appsettingAudioPlayFlagUpdatePID,
                 appsettingFlagUpdate, select_play_threadQ, update_data_entry)
import media.scene_end as _scene_end

try:
    import integrations.relay_audio_stream as _relay_audio
except Exception:   # a broken/missing streaming module must never take down playback
    class _RelayAudioNoop:
        def __getattr__(self, _name):
            return lambda *a, **k: None
    _relay_audio = _RelayAudioNoop()

log = logging.getLogger(__name__)

TICK_S = 0.25            # queue check cadence while idle (an event wakes it sooner)
RESPAWN_BACKOFF_S = 2.0  # after an mpv crash
FADE_IN = 'lavfi=[afade=type=in:duration=2]'   # same rise from silence as the classic engine


def _emit_nowplaying():
    try:
        import core.events as events
        from sql import get_now_playing
        events.emit('nowplaying', get_now_playing())
    except Exception:
        pass


def _switch_on():
    try:
        return int(appsettingAudioPlayFlag()[0][2]) == 1
    except Exception:
        return False


def _pdeathsig():
    try:
        import ctypes
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:
        pass


def mpv_args(sock, device=None):
    """The persistent audio-only mpv: idle, no window, IPC on `sock`."""
    args = ['mpv', '--idle=yes', '--no-terminal', '--no-video', '--force-window=no',
            '--input-ipc-server=' + sock, '--af=' + FADE_IN, '--volume=100', '--loop-file=no',
            '--keep-open=no']
    if device:
        args.append('--audio-device=' + device)
    return args


class MusicPlayer:
    """Supervisor for the persistent music mpv. `spawn`/`client` are
    injectable so the tests drive it with a fake mpv."""

    def __init__(self, spawn=None, client_factory=None, sleep=time.sleep, parent_pid=None):
        self.sock = socket_path('music')
        self._spawn = spawn or self._spawn_mpv
        self._client_factory = client_factory or (lambda: MpvClient(self.sock).connect(timeout=10))
        self._sleep = sleep
        self.parent_pid = parent_pid
        self.proc = None
        self.client = None
        self.playing = None          # the select_play_threadQ row of the loaded track
        self.device = None           # audio device the process was started/set with
        self._ended = []             # end-file events from the reader thread
        self._lock = threading.Lock()
        self.stopping = False

    # ── mpv lifecycle ──
    def _spawn_mpv(self, device):
        if os.name != 'nt':
            try:
                os.unlink(self.sock)     # a stale socket file from a crashed run
            except OSError:
                pass
        dev = None
        if device:
            dev = device if os.name == 'nt' else 'pulse/' + device
        kw = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
        if os.name != 'nt':
            kw['preexec_fn'] = _pdeathsig            # mpv dies with this worker
        return subprocess.Popen(mpv_args(self.sock, dev), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

    def ensure_mpv(self):
        alive = self.proc is not None and self.proc.poll() is None
        if alive and self.client is not None and self.client.connected:
            return True
        if self.client is not None:
            self.client.close()
            self.client = None
        if not alive:
            if self.proc is not None:
                log.warning('music mpv exited (%s) — respawning', self.proc.returncode)
                if self.playing is not None:
                    self._finish(self.playing, 'crash')
                self._sleep(RESPAWN_BACKOFF_S)
            self.device = _relay_audio.output_device() or None
            self.proc = self._spawn(self.device)
            appsettingAudioPlayFlagUpdatePID(self.proc.pid)
        try:
            self.client = self._client_factory()
        except MpvError as e:
            log.warning('music mpv IPC not reachable: %s', e)
            return False
        self.client.on_event('end-file', self._on_end_file)
        return True

    def _on_end_file(self, msg):
        with self._lock:
            self._ended.append(msg.get('reason', ''))

    # ── one supervisor step ──
    def step(self):
        """Advance the player once: handle finished tracks, then start the next
        queued track when the switch is on and nothing is loaded. Returns
        True when something happened (a test convenience)."""
        if not self.ensure_mpv():
            return False
        acted = False
        with self._lock:
            ended, self._ended = self._ended, []
        for reason in ended:
            if self.playing is not None:
                self._finish(self.playing, reason)
                acted = True
        if self.playing is None and _switch_on():
            row = select_play_threadQ()
            if len(row) == 0:
                self._drain()
            else:
                self._start(row)
            acted = True
        return acted

    def _start(self, row):
        song_id, path, volume, loops = row[0], row[1], row[7], row[8]
        # re-stored per track: the boot-time appsettings seed can overwrite the
        # value written at spawn, and the relay's Windows capture + the fade
        # gate read it (the classic engine wrote it per track too)
        appsettingAudioPlayFlagUpdatePID(self.proc.pid)
        appsettingFlagUpdate('currentsong', song_id)
        _relay_audio.on_track_start(song_id)
        device = _relay_audio.output_device() or None
        if device != self.device:
            # the relay's capture sink came up (or went away) since the spawn
            try:
                self.client.set('audio-device', (device if os.name == 'nt' else 'pulse/' + device) if device else 'auto')
                self.device = device
            except MpvError as e:
                log.warning('audio-device switch failed: %s', e)
        vol = int(max(0, min(100, volume)))
        loops = int(max(0, min(9999, loops)))
        try:
            self.client.set('volume', vol)
            self.client.set('loop-file', loops if loops > 0 else 'no')
            self.client.command('loadfile', path, 'replace')
        except MpvError as e:
            log.warning('loadfile failed for %s: %s', path, e)
            update_data_entry(row)          # count it played so the queue moves on
            appsettingFlagUpdate('currentsong', 0)
            _relay_audio.on_track_end()
            return
        self.playing = row
        log.info('playing %s (vol %s, loops %s)', path, vol, loops)
        _emit_nowplaying()

    def _finish(self, row, reason):
        self.playing = None
        _relay_audio.on_track_end()
        try:
            update_data_entry(row)
        except Exception as e:
            log.warning('update_data_entry failed: %s', e)
        log.info('track ended (%s)', reason or 'eof')
        _emit_nowplaying()

    def _drain(self):
        """Queue empty: the classic worker's drain bookkeeping."""
        appsettingAudioPlayFlagUpdate(0)
        appsettingFlagUpdate('currentsong', 0)
        _relay_audio.on_playback_stopped()
        _scene_end.notify_if_scene_ended()
        _emit_nowplaying()

    # ── worker loop ──
    def parent_alive(self):
        if not self.parent_pid:
            return True
        return pid_alive(self.parent_pid)

    def run(self):
        last_parent_check = 0.0
        while not self.stopping:
            try:
                self.step()
            except Exception as e:
                log.warning('music player step failed: %s', e)
                self._sleep(1.0)
            now = time.monotonic()
            if now - last_parent_check > 1.0:
                last_parent_check = now
                if not self.parent_alive():
                    break
            self._sleep(TICK_S)
        self.shutdown()

    def shutdown(self):
        self.stopping = True
        try:
            if self.client is not None:
                try:
                    self.client.command('quit', timeout=1.0)
                except MpvError:
                    pass
                self.client.close()
        finally:
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=3)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass


def threader(n, a):
    """Drop-in for player.threader (same (num, arr) signature): a[0] is the
    parent PID sentinel the classic worker probes."""
    appsettingAudioPlayFlagUpdate(0)
    parent = None
    try:
        parent = int(a[0]) or None
    except Exception:
        pass
    player = MusicPlayer(parent_pid=parent)

    def _term(signum, frame):
        player.stopping = True
    try:
        signal.signal(signal.SIGTERM, _term)
    except Exception:
        pass
    player.run()

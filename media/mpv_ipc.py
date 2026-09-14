r"""IPC to the two mpv instances, addressed by socket name (music / video).

Linux: /tmp/mpvsocket-<kind> (a unix socket); Windows: the same name as a
\\.\pipe\ named pipe. Both are mpv's JSON IPC (`--input-ipc-server`).

Two layers:

* `mpv_command(kind, 'seek 10')` — the fire-and-forget text contract the
  transport routes and the kill helpers have always used. A dead socket fails
  SILENTLY (an idle player is a no-op), and no `socat` is needed any more:
  the text is translated to a JSON command and written by Python.
* `MpvClient` — a persistent JSON IPC session with request/response matching,
  property observation and mpv's event stream, used by the persistent-player
  engine (player_ipc.py, `SP_PLAYER=ipc`).

Lives in its own module so the transport routes (routers/public.py), the kill
helpers (sql.py) and the player workers share it without an import cycle.
"""
import json
import os
import socket
import threading
import time

import core.config as config


class MpvError(Exception):
    pass


def socket_path(kind):
    return config.mpv_socket(kind)


def _parse_text_command(command):
    """'add volume -10' -> ['add', 'volume', -10]; numbers become numbers
    (mpv's JSON API wants them typed, the text API coerced them)."""
    out = []
    for tok in str(command).split():
        try:
            out.append(int(tok))
            continue
        except ValueError:
            pass
        try:
            out.append(float(tok))
            continue
        except ValueError:
            pass
        out.append(tok)
    return out


# ── transport ─────────────────────────────────────────────────────────────────

class _Transport:
    """Line-oriented duplex channel to one mpv: unix socket or named pipe."""

    def __init__(self, path, timeout=2.0):
        self.path = path
        if os.name == 'nt':
            self._pipe = open(path, 'r+b', buffering=0)
            self._sock = None
        else:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect(path)
            self._pipe = None
        self._buf = b''

    def write_line(self, text):
        data = text.encode('utf-8') + b'\n'
        if self._pipe is not None:
            self._pipe.write(data)
        else:
            self._sock.sendall(data)

    def read_line(self, timeout=None):
        """One JSON line, or None on timeout; raises ConnectionError when the
        peer is gone."""
        if self._pipe is not None:
            line = self._pipe.readline()
            if not line:
                raise ConnectionError('mpv pipe closed')
            return line.decode('utf-8', 'replace').rstrip('\r\n')
        self._sock.settimeout(timeout)
        while b'\n' not in self._buf:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError('mpv socket closed')
            self._buf += chunk
        line, self._buf = self._buf.split(b'\n', 1)
        return line.decode('utf-8', 'replace')

    def close(self):
        try:
            if self._pipe is not None:
                self._pipe.close()
            else:
                self._sock.close()
        except Exception:
            pass


# ── persistent JSON client ────────────────────────────────────────────────────

class MpvClient:
    """One connection to one mpv. Thread-safe; a reader thread demultiplexes
    replies (by request_id) from events (`on_event`) and observed
    properties (`observe`)."""

    def __init__(self, kind_or_path):
        self.path = kind_or_path if ('/' in kind_or_path or '\\' in kind_or_path) else socket_path(kind_or_path)
        self._tr = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._pending = {}          # request_id -> (Event, [reply])
        self._event_handlers = {}   # event name -> [callbacks]
        self._observers = {}        # observe id -> (name, callback)
        self._reader = None
        self._closed = threading.Event()

    # connection ---------------------------------------------------------------
    def connect(self, timeout=5.0, poll=0.1):
        """Wait up to `timeout` s for the socket to appear and accept."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                self._tr = _Transport(self.path)
                break
            except (OSError, ConnectionError) as e:
                last = e
                time.sleep(poll)
        if self._tr is None:
            raise MpvError(f'mpv not reachable at {self.path}: {last}')
        self._closed.clear()
        self._reader = threading.Thread(target=self._read_loop, name=f'mpv-ipc-{os.path.basename(self.path)}', daemon=True)
        self._reader.start()
        return self

    @property
    def connected(self):
        return self._tr is not None and not self._closed.is_set()

    def close(self):
        self._closed.set()
        tr, self._tr = self._tr, None
        if tr:
            tr.close()
        for ev, box in list(self._pending.values()):
            box.append({'error': 'closed'})
            ev.set()
        self._pending.clear()

    # requests -------------------------------------------------------------------
    def command(self, *args, timeout=3.0):
        """Send a command, return its `data` (raises MpvError on an mpv error,
        a timeout, or a closed connection)."""
        if not self.connected:
            raise MpvError('not connected')
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            ev, box = threading.Event(), []
            self._pending[rid] = (ev, box)
            try:
                self._tr.write_line(json.dumps({'command': list(args), 'request_id': rid}))
            except Exception as e:
                self._pending.pop(rid, None)
                self.close()
                raise MpvError(f'write failed: {e}') from e
        if not ev.wait(timeout):
            self._pending.pop(rid, None)
            raise MpvError(f'timeout waiting for {args[0]}')
        reply = box[0]
        if reply.get('error') not in (None, 'success'):
            raise MpvError(f'{args}: {reply.get("error")}')
        return reply.get('data')

    def get(self, prop, default=None):
        try:
            return self.command('get_property', prop)
        except MpvError:
            return default

    def set(self, prop, value):
        return self.command('set_property', prop, value)

    def observe(self, prop, callback):
        """callback(name, value) on every change (mpv sends the current value first)."""
        with self._lock:
            oid = len(self._observers) + 1
            self._observers[oid] = (prop, callback)
        self.command('observe_property', oid, prop)
        return oid

    def on_event(self, name, callback):
        """callback(event_dict) for mpv events such as end-file / file-loaded."""
        self._event_handlers.setdefault(name, []).append(callback)

    # reader ---------------------------------------------------------------------
    def _read_loop(self):
        while not self._closed.is_set():
            try:
                line = self._tr.read_line(timeout=0.5)
            except (ConnectionError, OSError, AttributeError):
                break
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            rid = msg.get('request_id')
            if rid is not None:
                pend = self._pending.pop(rid, None)
                if pend:
                    pend[1].append(msg)
                    pend[0].set()
                continue
            ev = msg.get('event')
            if ev == 'property-change':
                obs = self._observers.get(msg.get('id'))
                if obs:
                    try:
                        obs[1](obs[0], msg.get('data'))
                    except Exception:
                        pass
            if ev:
                for cb in list(self._event_handlers.get(ev, ())):
                    try:
                        cb(msg)
                    except Exception:
                        pass
        self._closed.set()
        for ev_, box in list(self._pending.values()):
            box.append({'error': 'closed'})
            ev_.set()
        self._pending.clear()


# ── the fire-and-forget text contract ─────────────────────────────────────────

def mpv_command(kind, command):
    """Send one text command ('seek 10', 'cycle pause', 'add volume -10') to
    the `kind` player. Silent no-op when no player is listening — same
    contract the transport controls have always had against an idle player."""
    try:
        tr = _Transport(socket_path(kind), timeout=1.0)
    except (OSError, ConnectionError):
        return False
    try:
        tr.write_line(json.dumps({'command': _parse_text_command(command)}))
        return True
    except Exception:
        return False
    finally:
        tr.close()


# 12 steps of `add volume -10` reach silence from ANY starting volume (mpv
# clamps at 0), so the current volume never has to be read back off the
# socket.
_FADE_STEPS = 12
_FADE_SECONDS = 1.2


def music_fade_out():
    """Taper the music player to silence right before a kill/stop, so skips
    and scene switches don't cut a song off mid-waveform. The relay stream
    captures mpv's output, so remote players hear the same taper.

    No restore afterwards: the classic engine spawns the next track with its
    own --volume, the persistent engine resets `volume` before every loadfile.
    Gated on a live player — against a dead socket the commands are no-ops
    and the fade would only burn its sleep time."""
    try:
        from sql import appsettingAudioPlayPID
        from core.procutil import pid_alive
        if not pid_alive(int(appsettingAudioPlayPID()[0][2])):
            return
    except Exception:
        return
    if config.PLAYER == 'ipc':
        try:
            from sql import appsettingFlagGet
            if int(appsettingFlagGet('currentsong') or 0) <= 0:
                return          # persistent mpv is alive but idle — nothing to taper
        except Exception:
            pass
    for _ in range(_FADE_STEPS):
        if not mpv_command('music', 'add volume -10'):
            return
        time.sleep(_FADE_SECONDS / _FADE_STEPS)


def music_stop():
    """Persistent engine: fade, then `stop` — the player worker sees the
    end-file event and either loads the next queued track (skip) or drains
    (kill, since the queue was cleared first). Classic engine: kill the
    per-track process instead (sql.queue_next does that)."""
    music_fade_out()
    mpv_command('music', 'stop')

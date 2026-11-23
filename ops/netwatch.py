"""Wi-Fi fallback hotspot daemon (runs as root: sceneplay_netwatch.service).

If this box cannot reach any network, raise an open `ScenePlay-XXXX` hotspot so
a phone can join it and pick the real Wi-Fi from /setup/wifi. It is a separate
service from ScenePlay on purpose: the way back onto the network must still
work when the app itself does not start.

Modes (status()['mode']):
  starting    boot grace: NetworkManager gets a chance to autoconnect first
  client      on a network (Wi-Fi or Ethernet) — nothing to do
  waiting     lost the network; the hotspot comes up after LOST_GRACE
  offline     no network and the fallback is switched off
  hotspot     fallback hotspot is up (open); every RETRY_EVERY with no phone
              connected, it steps down to look for a saved network
  play        "hotspot play mode": the DM asked for the hotspot on purpose
              (optionally WPA2); it never steps down by itself
  connecting  joining a network the user picked
  no_wifi     no Wi-Fi adapter / NetworkManager not running

The app talks to it over a unix socket (SOCKET_PATH, owned by the ScenePlay
user, 0600): one JSON line in, one JSON line out. Settings live in
<instance>/network.json, written by the app, read here every tick.

Stdlib only — the service runs the system python, not the venv.
"""
import json
import os
import queue
import socket
import socketserver
import sys
import threading
import time

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import core.config as config  # noqa: E402
from ops import netctl  # noqa: E402

SOCKET_PATH = '/run/sceneplay-netwatch.sock'
SETTINGS_FILE = 'network.json'
TICK = 5
BOOT_GRACE = 75
LOST_GRACE = 45
RETRY_EVERY = 300
DEFAULTS = {'fallback_enabled': True, 'play_mode': False, 'play_password': ''}


def settings_path():
    return os.path.join(config.INSTANCE_DIR, SETTINGS_FILE)


def load_settings(path=None):
    path = path or settings_path()
    data = dict(DEFAULTS)
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data['fallback_enabled'] = bool(raw.get('fallback_enabled', True))
            data['play_mode'] = bool(raw.get('play_mode', False))
            pw = raw.get('play_password') or ''
            data['play_password'] = pw if isinstance(pw, str) else ''
    except (OSError, ValueError):
        pass
    return data


def save_settings(data, path=None):
    """App side. 0600: the play-mode password is in here."""
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}, f)
    os.replace(tmp, path)


def hotspot_ssid(hwaddr):
    tail = ''.join(c for c in (hwaddr or '') if c.isalnum())[-4:].upper()
    return 'ScenePlay-' + (tail or 'Setup')


def _now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S')


class NetWatch:
    def __init__(self, nm, settings_file=None, clock=time.monotonic, sleep=time.sleep,
                 boot_grace=BOOT_GRACE, lost_grace=LOST_GRACE, retry_every=RETRY_EVERY):
        self.nm = nm
        self.settings_file = settings_file
        self.clock = clock
        self.sleep = sleep
        self.boot_grace = boot_grace
        self.lost_grace = lost_grace
        self.retry_every = retry_every
        self.started = clock()
        self.mode = 'starting'
        self.dev = None
        self.net = {'ethernet': None, 'wifi': None, 'hotspot': False}
        self.lost_since = self.started   # until seen online, the box counts as offline since boot
        self.ap_kind = None          # 'fallback' | 'play' — what WE raised
        self.ap_password = None
        self.ap_since = None
        self.ssid = None
        self.scan_cache = []
        self.scan_at = None
        self.last_attempt = None
        self.last_error = None
        self._ssid_of = {}            # profile name -> SSID ('preconfigured' -> 'Home')
        self.jobs = queue.Queue()
        self.lock = threading.RLock()

    # ── helpers ──
    def settings(self):
        return load_settings(self.settings_file)

    def _ap_up(self, kind, password=None):
        ok, msg = self.nm.hotspot_up(self.dev, self.ssid, password or None)
        if ok:
            self.ap_kind, self.ap_password, self.ap_since = kind, password or None, self.clock()
            self.mode = 'play' if kind == 'play' else 'hotspot'
            self.last_error = None
            log(f'hotspot up ({kind}) as {self.ssid}')
        else:
            self.last_error = f'hotspot failed: {msg}'
            log(self.last_error)
        return ok

    def _ap_down(self):
        self.nm.hotspot_down()
        self.ap_kind = self.ap_password = self.ap_since = None
        self.sleep(3)

    def _refresh_scan(self):
        nets = self.nm.scan(self.dev)
        if nets:
            self.scan_cache, self.scan_at = nets, self.clock()
        return nets

    def _connected(self):
        return bool(self.net['ethernet'] or self.net['wifi'])

    # ── main loop ──
    def tick(self):
        with self.lock:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                job = None
            if job is not None:
                self._run_job(job)
                return
            self._tick()

    def _tick(self):
        now = self.clock()
        self.dev = self.nm.wifi_device()
        if not self.dev:
            self.mode = 'no_wifi'
            return
        if self.ssid is None:
            self.ssid = hotspot_ssid(self.nm.hwaddr(self.dev))
        s = self.settings()
        self.net = self.nm.state(self.dev)

        if s['play_mode']:
            want_pw = s['play_password'] or None
            if not self.net['hotspot'] or self.ap_kind != 'play' or self.ap_password != want_pw:
                self._ap_up('play', want_pw)
            else:
                self.mode = 'play'
            return

        if self.net['hotspot']:
            if self.ap_kind is None:
                self.ap_kind, self.ap_since = 'fallback', now     # daemon restarted under its own AP
            if self.ap_kind == 'play' or not s['fallback_enabled'] or self.net['ethernet']:
                self._ap_down()
                self.lost_since = self.clock()
                self.mode = 'waiting'
                return
            self.mode = 'hotspot'
            if now - self.ap_since >= self.retry_every and self.nm.station_count(self.dev) == 0:
                self._retry_saved()
            return

        if self._connected():
            self.mode = 'client'
            self.lost_since = None
            return

        if self.lost_since is None:
            self.lost_since = now
        if not s['fallback_enabled']:
            self.mode = 'offline'
            return
        in_boot = now - self.started < self.boot_grace
        self.mode = 'starting' if in_boot else 'waiting'
        if not in_boot and now - self.lost_since >= self.lost_grace:
            self._refresh_scan()
            self._ap_up('fallback')

    def _retry_saved(self):
        """Step the hotspot down, look for a saved network, come back if none."""
        log('hotspot idle: looking for a saved network')
        self._ap_down()
        self.net = self.nm.state(self.dev)
        if self._connected():                         # NetworkManager autoconnected on its own
            self.mode, self.lost_since = 'client', None
            return
        visible = {n['ssid'] for n in self._refresh_scan()}
        for saved in self.nm.saved_wifi():
            if saved['ssid'] in visible:
                ok, _ = self.nm.up(saved['name'], self.dev, wait=30)
                if ok:
                    self.net = self.nm.state(self.dev)
                    self.mode, self.lost_since = 'client', None
                    log(f'rejoined {saved["name"]}')
                    return
        self._ap_up('fallback')

    def _run_job(self, job):
        if job.get('cmd') != 'connect':
            return
        ssid = job['ssid']
        self.dev = self.dev or self.nm.wifi_device()
        if not self.dev:
            self.last_attempt = {'ssid': ssid, 'ok': False, 'error': 'No Wi-Fi adapter.', 'at': _now_str()}
            return
        if self.ssid is None:
            self.ssid = hotspot_ssid(self.nm.hwaddr(self.dev))
        was_ap = self.nm.state(self.dev)['hotspot']
        self.mode = 'connecting'
        self.last_attempt = {'ssid': ssid, 'ok': None, 'error': None, 'at': _now_str()}
        if was_ap:
            self._ap_down()
        sec = next((n['security'] for n in self._refresh_scan() if n['ssid'] == ssid),
                   job.get('security') or '')
        ok, msg = self.nm.connect(self.dev, ssid, job.get('password') or '', bool(job.get('hidden')), sec)
        self.net = self.nm.state(self.dev)
        if ok:
            self.mode, self.lost_since = 'client', None
            self.last_attempt.update(ok=True, ip=self.nm.ip(self.dev))
            log(f'connected to {ssid}')
            return
        self.last_attempt.update(ok=False, error=msg)
        log(f'connect to {ssid} failed: {msg}')
        s = self.settings()
        if self._connected():
            self.mode = 'client'
        elif was_ap and s['fallback_enabled']:
            self._ap_up('fallback')                # straight back, the phone is waiting
        else:
            self.mode, self.lost_since = 'waiting', self.clock()

    # ── commands from the app ──
    def status(self):
        s = self.settings()
        ip = None
        if self.mode in ('hotspot', 'play'):
            ip = netctl.HOTSPOT_ADDR
        elif self.dev and self.mode == 'client':
            try:
                ip = self.nm.ip(self.dev)
            except Exception:
                ip = None
        wifi = self.net.get('wifi')
        if wifi and wifi not in self._ssid_of:
            try:
                self._ssid_of[wifi] = next((x['ssid'] for x in self.nm.saved_wifi() if x['name'] == wifi), wifi)
            except Exception:
                pass
        return {
            'available': self.mode != 'no_wifi',
            'mode': self.mode,
            'device': self.dev,
            'wifi': wifi,
            'wifi_ssid': self._ssid_of.get(wifi, wifi) if wifi else None,
            'ethernet': self.net.get('ethernet'),
            'ip': ip,
            'hostname': socket.gethostname(),
            'hotspot_ssid': self.ssid,
            'hotspot_open': not (self.mode == 'play' and self.ap_password),
            'fallback_enabled': s['fallback_enabled'],
            'play_mode': s['play_mode'],
            'last_attempt': self.last_attempt,
            'last_error': self.last_error,
            'scan_age': None if self.scan_at is None else int(self.clock() - self.scan_at),
        }

    def handle(self, req):
        cmd = (req or {}).get('cmd')
        if cmd == 'status':
            return {'ok': True, 'status': self.status()}
        if cmd == 'scan':
            with self.lock:
                if self.dev and self.mode not in ('hotspot', 'play', 'connecting'):
                    self._refresh_scan()      # scanning while an AP is up is not possible on one radio
                return {'ok': True, 'networks': self.scan_cache, 'age': self.status()['scan_age']}
        if cmd == 'saved':
            with self.lock:
                return {'ok': True, 'saved': self.nm.saved_wifi()}
        if cmd == 'forget':
            with self.lock:
                return {'ok': bool(self.nm.forget(str(req.get('name') or '')))}
        if cmd == 'connect':
            ssid = str(req.get('ssid') or '').strip()
            pw = str(req.get('password') or '')
            if not ssid or len(ssid.encode()) > 32:
                return {'ok': False, 'error': 'Network name must be 1–32 bytes.'}
            if pw and not 8 <= len(pw) <= 63:
                return {'ok': False, 'error': 'Wi-Fi passwords are 8–63 characters.'}
            self.last_attempt = {'ssid': ssid, 'ok': None, 'error': None, 'at': _now_str()}
            self.jobs.put({'cmd': 'connect', 'ssid': ssid, 'password': pw,
                           'hidden': bool(req.get('hidden')), 'security': req.get('security') or ''})
            return {'ok': True, 'queued': True}
        if cmd == 'reload':
            return {'ok': True}                  # settings are re-read every tick
        return {'ok': False, 'error': 'unknown command'}


# ── socket client (used by routers/network.py) ──
def request(cmd, timeout=5, path=None, **kw):
    """One request to the daemon, or None when it is not running (Windows,
    a box without the service, dev instances on another machine)."""
    path = path or SOCKET_PATH
    if os.name == 'nt' or not os.path.exists(path):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall((json.dumps({'cmd': cmd, **kw}) + '\n').encode())
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode() or 'null')
    except (OSError, ValueError):
        return None


# ── socket server + entry point ──
def log(msg):
    print(f'[netwatch] {msg}', flush=True)


def serve(watch, path=SOCKET_PATH, owner_uid=None):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                line = self.rfile.readline(65536)
                resp = watch.handle(json.loads(line.decode() or '{}'))
            except Exception as e:                                  # never kill the server
                resp = {'ok': False, 'error': str(e)}
            self.wfile.write((json.dumps(resp) + '\n').encode())

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socketserver.ThreadingUnixStreamServer(path, Handler)
    srv.daemon_threads = True
    os.chmod(path, 0o600)
    if owner_uid is not None:
        try:
            os.chown(path, owner_uid, -1)
        except OSError as e:
            log(f'chown socket failed: {e}')
    threading.Thread(target=srv.serve_forever, daemon=True, name='netwatch-sock').start()
    return srv


def main():
    nm = netctl.Nmcli()
    for _ in range(12):                         # NetworkManager may still be starting
        if nm.available():
            break
        time.sleep(5)
    else:
        log('NetworkManager is not running — nothing to do (needs Raspberry Pi OS Bookworm or newer)')
        return 0
    watch = NetWatch(nm, settings_path())
    serve(watch, owner_uid=os.stat(config.ROOT).st_uid)
    log('watching (fallback hotspot after %ss without a network)' % LOST_GRACE)
    while True:
        try:
            watch.tick()
        except Exception as e:
            log(f'tick failed: {e}')
        time.sleep(TICK)


if __name__ == '__main__':
    sys.exit(main())

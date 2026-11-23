"""Thin NetworkManager (nmcli) wrapper for the Wi-Fi fallback hotspot.

Only ops/netwatch.py (the root daemon) calls this. Stdlib only: the daemon runs
under the system python, not the venv. Every call is an argv list (never a
shell), so SSIDs and passwords are passed through verbatim.

Rules this module keeps:
  * the hotspot lives in ONE profile, HOTSPOT_NAME, which it owns outright;
  * a saved network is only ever deleted by forget() (an explicit user action)
    or when a brand-new profile this module just created fails to connect;
  * an existing profile whose password was changed and then failed gets its
    old secret back.
"""
import shutil
import subprocess

HOTSPOT_NAME = 'ScenePlay-Hotspot'
HOTSPOT_ADDR = '10.42.0.1'
WIFI_TYPE = '802-11-wireless'


def split_terse(line):
    """Split one `nmcli -t` line on unescaped ':' (nmcli escapes ':' and '\\'
    inside values with a backslash)."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == '\\':
            esc = True
        elif ch == ':':
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append(''.join(cur))
    return out


def parse_scan(text):
    """`IN-USE,SSID,SIGNAL,SECURITY` rows -> one entry per SSID (strongest
    signal wins), hidden (empty) SSIDs dropped, strongest first."""
    best = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        f = split_terse(line)
        if len(f) < 4:
            continue
        in_use, ssid, signal, security = f[0], f[1], f[2], ':'.join(f[3:])
        if not ssid:
            continue
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        sec = '' if security.strip() in ('', '--') else security.strip()
        cur = best.get(ssid)
        if cur is None or sig > cur['signal']:
            best[ssid] = {'ssid': ssid, 'signal': sig, 'security': sec,
                          'in_use': in_use.strip() == '*' or (cur or {}).get('in_use', False)}
        elif in_use.strip() == '*':
            cur['in_use'] = True
    return sorted(best.values(), key=lambda n: (-n['signal'], n['ssid'].lower()))


def parse_devices(text):
    """`DEVICE,TYPE,STATE,CONNECTION` rows -> list of dicts."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        f = split_terse(line)
        if len(f) < 4:
            continue
        rows.append({'device': f[0], 'type': f[1], 'state': f[2], 'connection': ':'.join(f[3:])})
    return rows


def key_mgmt_for(security, password):
    """nmcli key-mgmt for a scan SECURITY string, or None for an open network."""
    if not password:
        return None
    sec = (security or '').upper()
    if 'WPA3' in sec and 'WPA2' not in sec and 'WPA1' not in sec:
        return 'sae'
    return 'wpa-psk'


def friendly_error(err):
    """nmcli's activation errors in words a DM can act on."""
    e = (err or '').lower()
    if 'secrets were required' in e or 'no secrets' in e or '802-1x supplicant' in e \
            or 'psk: property is invalid' in e:
        return 'Wrong password (the network rejected it).'
    if 'no network with ssid' in e or 'not found' in e:
        return 'Network not found — is it in range?'
    if 'timeout' in e or 'timed out' in e:
        return 'Timed out joining the network.'
    if 'ip configuration could not be reserved' in e or 'dhcp' in e:
        return 'Joined the Wi-Fi, but it did not hand out an address (DHCP).'
    first = (err or '').strip().splitlines()
    return first[0][:200] if first else 'Could not connect.'


class Nmcli:
    """Real nmcli. Tests use a fake with the same methods."""

    def __init__(self, binary='nmcli', runner=None):
        self.binary = binary
        self._runner = runner or self._run

    @staticmethod
    def _run(argv, timeout):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, '', 'timed out'
        except OSError as e:
            return 127, '', str(e)

    def nm(self, *args, timeout=20):
        return self._runner([self.binary, *args], timeout)

    # ── facts ──
    def available(self):
        if not shutil.which(self.binary):
            return False
        rc, out, _ = self.nm('-t', '-f', 'RUNNING', 'general', timeout=10)
        return rc == 0 and out.strip() == 'running'

    def devices(self):
        rc, out, _ = self.nm('-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', timeout=10)
        return parse_devices(out) if rc == 0 else []

    def wifi_device(self):
        for d in self.devices():
            if d['type'] == 'wifi':
                return d['device']
        return None

    def state(self, dev):
        """{'ethernet': name|None, 'wifi': name|None, 'hotspot': bool}"""
        st = {'ethernet': None, 'wifi': None, 'hotspot': False}
        for d in self.devices():
            if not d['state'].startswith('connected'):
                continue
            if d['type'] == 'ethernet' and not st['ethernet']:
                st['ethernet'] = d['connection'] or d['device']
            elif d['type'] == 'wifi' and d['device'] == dev:
                if d['connection'] == HOTSPOT_NAME:
                    st['hotspot'] = True
                else:
                    st['wifi'] = d['connection']
        return st

    def ip(self, dev):
        rc, out, _ = self.nm('-g', 'IP4.ADDRESS', 'device', 'show', dev, timeout=10)
        if rc != 0 or not out.strip():
            return None
        return out.strip().split('|')[0].strip().split('/')[0] or None

    def hwaddr(self, dev):
        rc, out, _ = self.nm('-g', 'GENERAL.HWADDR', 'device', 'show', dev, timeout=10)
        return out.strip().replace('\\', '') if rc == 0 else ''

    def scan(self, dev, rescan=True):
        rc, out, _ = self.nm('-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list',
                             'ifname', dev, '--rescan', 'yes' if rescan else 'no', timeout=30)
        return parse_scan(out) if rc == 0 else []

    def saved_wifi(self):
        """[{'name', 'ssid'}] for every saved Wi-Fi profile except the hotspot."""
        rc, out, _ = self.nm('-t', '-f', 'NAME,TYPE', 'connection', 'show', timeout=10)
        if rc != 0:
            return []
        res = []
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) < 2 or f[-1] != WIFI_TYPE:
                continue
            name = ':'.join(f[:-1])
            if name == HOTSPOT_NAME:
                continue
            rc2, ssid, _ = self.nm('-g', '802-11-wireless.ssid', 'connection', 'show', name, timeout=10)
            ssid = ssid.strip().replace('\\:', ':') if rc2 == 0 else ''
            res.append({'name': name, 'ssid': ssid or name})
        return res

    def station_count(self, dev):
        """Phones associated to our hotspot (0 when `iw` is missing)."""
        if not shutil.which('iw'):
            return 0
        rc, out, _ = self._runner(['iw', 'dev', dev, 'station', 'dump'], 10)
        return sum(1 for ln in out.splitlines() if ln.startswith('Station ')) if rc == 0 else 0

    # ── actions ──
    def up(self, name, dev, wait=40):
        rc, out, err = self.nm('--wait', str(wait), 'connection', 'up', name, 'ifname', dev,
                               timeout=wait + 10)
        return rc == 0, (err or out)

    def hotspot_up(self, dev, ssid, password=None):
        self.nm('radio', 'wifi', 'on', timeout=10)
        self.nm('connection', 'delete', HOTSPOT_NAME, timeout=15)
        args = ['connection', 'add', 'type', 'wifi', 'ifname', dev, 'con-name', HOTSPOT_NAME,
                'autoconnect', 'no', 'ssid', ssid,
                '802-11-wireless.mode', 'ap', '802-11-wireless.band', 'bg',
                'ipv4.method', 'shared', 'ipv4.addresses', HOTSPOT_ADDR + '/24',
                'ipv6.method', 'ignore']
        if password:
            # brcmfmac (every Pi) only does WPA2-CCMP in AP mode and chokes on PMF
            args += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password,
                     'wifi-sec.proto', 'rsn', 'wifi-sec.pairwise', 'ccmp',
                     'wifi-sec.group', 'ccmp', 'wifi-sec.pmf', 'disable']
        rc, out, err = self.nm(*args, timeout=20)
        if rc != 0:
            return False, err or out
        return self.up(HOTSPOT_NAME, dev, wait=30)

    def hotspot_down(self):
        rc, out, err = self.nm('connection', 'down', HOTSPOT_NAME, timeout=20)
        return rc == 0

    def _secret(self, name):
        rc, out, _ = self.nm('-s', '-g', '802-11-wireless-security.key-mgmt,802-11-wireless-security.psk',
                             'connection', 'show', name, timeout=10)
        lines = out.splitlines() if rc == 0 else []
        km = lines[0].strip() if lines else ''
        psk = lines[1] if len(lines) > 1 else ''
        return km, psk

    def connect(self, dev, ssid, password='', hidden=False, security=''):
        """Join `ssid`. Returns (ok, message). Reuses the saved profile for that
        SSID when there is one (Raspberry Pi Imager names its profile
        'preconfigured'), creating one otherwise."""
        existing = next((s['name'] for s in self.saved_wifi() if s['ssid'] == ssid), None)
        km = key_mgmt_for(security, password)
        if existing is None:
            name = ssid
            args = ['connection', 'add', 'type', 'wifi', 'ifname', dev, 'con-name', name, 'ssid', ssid,
                    'connection.autoconnect', 'yes']
            if hidden:
                args += ['802-11-wireless.hidden', 'yes']
            if km:
                args += ['wifi-sec.key-mgmt', km, 'wifi-sec.psk', password]
            rc, out, err = self.nm(*args, timeout=20)
            if rc != 0:
                return False, friendly_error(err or out)
            ok, msg = self.up(name, dev)
            if not ok:
                self.nm('connection', 'delete', name, timeout=15)
                return False, friendly_error(msg)
            return True, 'Connected'
        name = existing
        old_km, old_psk = self._secret(name)
        if password:
            self.nm('connection', 'modify', name, 'wifi-sec.key-mgmt', km, 'wifi-sec.psk', password,
                    timeout=15)
        if hidden:
            self.nm('connection', 'modify', name, '802-11-wireless.hidden', 'yes', timeout=15)
        ok, msg = self.up(name, dev)
        if not ok and password:
            if old_km:
                self.nm('connection', 'modify', name, 'wifi-sec.key-mgmt', old_km,
                        'wifi-sec.psk', old_psk, timeout=15)
            else:
                self.nm('connection', 'modify', name, 'remove', '802-11-wireless-security', timeout=15)
        return (True, 'Connected') if ok else (False, friendly_error(msg))

    def forget(self, name):
        if name == HOTSPOT_NAME or name not in {s['name'] for s in self.saved_wifi()}:
            return False
        rc, _, _ = self.nm('connection', 'delete', name, timeout=15)
        return rc == 0

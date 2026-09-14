#!/usr/bin/env python3
"""GET-parity between a 1.x Flask instance and this app on the SAME database copy.

  .venv/bin/python scripts/parity.py --flask http://127.0.0.1:8099 --new http://127.0.0.1:8087 \
      --user yllonnoce --password x [--only /api/scenes,/api/campaigns] [--verbose]

Logs in to Flask with a session cookie and to the new app with a JWT, GETs every path
in SAFE_GETS from both, strips volatile fields, and prints a unified diff per path that
differs. Exit code 1 when anything differs. Never calls a mutating endpoint."""
import argparse
import difflib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# (path, auth-class) — auth: 'open' | 'player' | 'dm'. Mutating GETs are deliberately absent
# (/activatescenes, /nextsong, /nextvideo, /killqueue, keepmusic on/off, /processyt,
#  /api/serverroleaddrow, /api/lights-off, restart-app, /backups/*).
SAFE_GETS = [
    ('/api/server-info', 'open'), ('/api/scenes', 'open'), ('/api/scenes/queue-states', 'open'),
    ('/api/campaigns', 'open'), ('/api/getcampaignSelect', 'open'), ('/api/music', 'open'),
    ('/api/videomedia', 'open'), ('/api/musicScene', 'open'), ('/api/videoScene', 'open'),
    ('/api/genre', 'open'), ('/api/dnLoadStatus', 'open'), ('/api/serverIP', 'open'),
    ('/api/serverrole', 'open'), ('/api/scenePattern', 'open'), ('/api/led/patterns', 'open'),
    ('/api/wledPattern', 'open'), ('/api/effects', 'open'), ('/api/pallettes', 'open'),
    ('/api/cronSchedule', 'open'), ('/api/ledconfig', 'open'), ('/api/ledconfigmodel', 'open'),
    ('/api/songandvideocount', 'open'), ('/api/nowplaying', 'open'), ('/api/downloads/status', 'open'),
    ('/api/chimes', 'open'), ('/utilities/assets/api/list', 'open'), ('/api/smart-scenes/facets', 'open'),
    ('/api/pingnetwork/status', 'open'), ('/isAlive', 'open'),
    ('/ttrpg/dice/feed', 'player'), ('/ttrpg/dice/system', 'player'),
    ('/ttrpg/battlemap/relay-rolls', 'player'), ('/ttrpg/textures/manifest', 'player'),
    ('/ttrpg/reference/spells/search?q=fire', 'player'), ('/ttrpg/reference/weapons/search?q=sword', 'player'),
    ('/ttrpg/reference/lookup/conditions?q=&limit=15', 'player'), ('/ttrpg/monsters/sync/status', 'player'),
    ('/ttrpg/battlemap/api/maps', 'dm'), ('/ttrpg/battlemap/relay-presence', 'dm'),
    ('/ttrpg/monsters/search?q=goblin', 'dm'), ('/ttrpg/obs/api/state', 'dm'), ('/ttrpg/obs/api/closeups', 'dm'),
    ('/ttrpg/relay/api/health', 'dm'), ('/ttrpg/relay/api/presence', 'dm'), ('/ttrpg/ai/status', 'dm'),
]

VOLATILE_KEYS = {'pid', 'ospid', 'version', 'os', 'machine', 'cores', 'PingTime', 'playedDTTM', 'ts', 'timestamp',
                 'updated_at', 'created_at', 'rolled_at', 'checked_at', 'uptime', 'last_seen', 'since'}
HOST_RE = re.compile(r'https?://[^/"\s]+')
VER_RE = re.compile(r'\?v=\d+')


def normalise(obj):
    if isinstance(obj, dict):
        return {k: normalise(v) for k, v in sorted(obj.items()) if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [normalise(x) for x in obj]
    if isinstance(obj, str):
        return VER_RE.sub('', HOST_RE.sub('http://HOST', obj))
    return obj


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.cookie = None
        self.bearer = None

    def _req(self, method, path, data=None, form=False):
        url = self.base + path
        headers = {}
        body = None
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode()
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
            else:
                body = json.dumps(data).encode()
                headers['Content-Type'] = 'application/json'
        if self.cookie:
            headers['Cookie'] = self.cookie
        if self.bearer:
            headers['Authorization'] = 'Bearer ' + self.bearer
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(self, path):
        status, _h, raw = self._req('GET', path)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw[:200].decode('utf-8', 'replace')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def login_flask(c, user, pw):
    status, headers, _ = c._req('POST', '/login', {'username': user, 'password': pw}, form=True)
    cookies = [re.match(r'[^;]+', v).group(0) for v in headers.get_all('Set-Cookie') or []]
    if status not in (200, 302) or not any(v.startswith('session=') for v in cookies):
        sys.exit(f'flask login failed (status {status}) — is 1.x on that port and are the credentials right?')
    c.cookie = '; '.join(cookies)


def login_new(c, user, pw):
    status, _h, raw = c._req('POST', '/api/v1/auth/login', {'username': user, 'password': pw})
    if status != 200:
        sys.exit(f'new-app login failed (status {status}): {raw[:200]!r}')
    c.bearer = json.loads(raw)['token']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--flask', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--user', default='yllonnoce')
    ap.add_argument('--password', default='x')
    ap.add_argument('--only', default='')
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()
    f, n = Client(a.flask), Client(a.new)
    login_flask(f, a.user, a.password)
    login_new(n, a.user, a.password)
    only = {p.strip() for p in a.only.split(',') if p.strip()}
    diffs = 0
    for path, _auth in SAFE_GETS:
        if only and path.split('?')[0] not in only:
            continue
        fs, fd = f.get(path)
        ns, nd = n.get(path)
        fj, nj = json.dumps(normalise(fd), indent=1, sort_keys=True), json.dumps(normalise(nd), indent=1, sort_keys=True)
        if fs == ns and fj == nj:
            if a.verbose:
                print(f'OK   {path} ({fs})')
            continue
        diffs += 1
        print(f'DIFF {path}: flask {fs} vs new {ns}')
        for line in difflib.unified_diff(fj.splitlines(), nj.splitlines(), 'flask', 'new', lineterm='', n=2):
            print('   ' + line)
    print(f'{diffs} path(s) differ out of {len(SAFE_GETS) if not only else len(only)}')
    sys.exit(1 if diffs else 0)


if __name__ == '__main__':
    main()

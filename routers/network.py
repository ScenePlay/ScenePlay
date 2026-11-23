"""Wi-Fi setup + fallback hotspot API (/api/v1/network/*) and the captive
setup page (/setup/wifi).

The root daemon ops/netwatch.py owns every network change; this router only
relays requests to it over its unix socket and never runs nmcli itself.

Access:
  * status is open (the setup page and the Utilities card both read it);
  * scan / connect are open ONLY while the box is in fallback-hotspot mode —
    nobody can log in from a phone on a box with no network, and the open
    hotspot is the gate. Otherwise they are DM-only, so a LAN or play-mode
    guest cannot re-point the box at another network;
  * saved / forget / settings are always DM-only.
Writes are refused on instances started with SP_INTEGRATIONS=0 (make dev,
tests): a dev server must never drive the live box's network.
"""
import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

import core.config as config
from ops import netwatch
from routers._util import json_body
from security.deps import ApiError, get_current_user, require_dm

router = APIRouter()

SETUP_PAGE = os.path.join(config.WEB_DIR, 'setup', 'wifi.html')


def _ask(cmd, timeout=5, **kw):
    return netwatch.request(cmd, timeout=timeout, **kw)


def _writes_allowed():
    return config.INTEGRATIONS and os.name != 'nt'


def _status():
    r = _ask('status', timeout=3)
    if not r or not r.get('ok'):
        reason = ('Windows manages Wi-Fi itself.' if os.name == 'nt'
                  else 'The ScenePlay network service is not installed or not running.')
        return {'available': False, 'mode': 'unavailable', 'reason': reason}
    return r['status']


def _setup_open(st):
    return bool(st.get('available')) and st.get('mode') == 'hotspot'


def setup_or_dm(user=Depends(get_current_user)):
    if user is not None and user.is_dm():
        return user
    if _setup_open(_status()):
        return None
    if user is None:
        raise ApiError(401, 'login required', code='login_required')
    raise ApiError(403, 'DM only', code='dm_required')


def _need_writes():
    if not _writes_allowed():
        raise ApiError(409, 'Network control is off on this instance.', code='network_disabled')


def _need_daemon(resp):
    if resp is None:
        raise ApiError(503, 'The ScenePlay network service is not running.', code='netwatch_down')
    return resp


@router.get('/setup/wifi', include_in_schema=False)
def setup_page():
    return FileResponse(SETUP_PAGE, media_type='text/html')


@router.get('/api/v1/network/status')
def api_status():
    st = _status()
    st['setup_open'] = _setup_open(st)
    st['writes_allowed'] = _writes_allowed()
    return st


@router.get('/api/v1/network/scan')
def api_scan(user=Depends(setup_or_dm)):
    r = _need_daemon(_ask('scan', timeout=45))
    return {'networks': r.get('networks') or [], 'age': r.get('age')}


@router.post('/api/v1/network/connect')
def api_connect(data: dict = Depends(json_body), user=Depends(setup_or_dm)):
    _need_writes()
    ssid = str(data.get('ssid') or '').strip()
    if not ssid:
        raise ApiError(400, 'Pick a network first.', code='bad_request')
    r = _need_daemon(_ask('connect', ssid=ssid, password=str(data.get('password') or ''),
                          hidden=bool(data.get('hidden')), security=str(data.get('security') or '')))
    if not r.get('ok'):
        raise ApiError(400, r.get('error') or 'Could not start connecting.', code='bad_request')
    return {'ok': True}


@router.get('/api/v1/network/saved')
def api_saved(user=Depends(require_dm)):
    r = _ask('saved', timeout=10)
    return {'saved': (r or {}).get('saved') or [], 'available': r is not None}


@router.post('/api/v1/network/forget')
def api_forget(data: dict = Depends(json_body), user=Depends(require_dm)):
    _need_writes()
    name = str(data.get('name') or '')
    r = _need_daemon(_ask('forget', timeout=15, name=name))
    if not r.get('ok'):
        raise ApiError(400, 'No saved network by that name.', code='not_found')
    return {'ok': True}


def _public_settings(s):
    return {'fallback_enabled': s['fallback_enabled'], 'play_mode': s['play_mode'],
            'has_play_password': bool(s['play_password'])}


@router.get('/api/v1/network/settings')
def api_settings(user=Depends(require_dm)):
    return _public_settings(netwatch.load_settings())


@router.post('/api/v1/network/settings')
def api_settings_save(data: dict = Depends(json_body), user=Depends(require_dm)):
    _need_writes()
    s = netwatch.load_settings()
    if 'fallback_enabled' in data:
        s['fallback_enabled'] = bool(data['fallback_enabled'])
    if 'play_mode' in data:
        s['play_mode'] = bool(data['play_mode'])
    if 'play_password' in data:
        pw = data['play_password']
        pw = '' if pw is None else str(pw)
        if pw and not 8 <= len(pw) <= 63:
            raise ApiError(400, 'Hotspot passwords are 8–63 characters (blank = open).', code='bad_request')
        s['play_password'] = pw
    netwatch.save_settings(s)
    _ask('reload', timeout=2)
    return _public_settings(s)

"""Producer console API — the live surface a second person runs the stream
from (/ttrpg/producer, spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md).

Lifecycle: the first console to open turns OBS Studio Mode and the audio
meter stream on and pauses auto-cam; STUDIO_OFF_GRACE_S after the last console
closes (or stops pinging) everything is put back. The rest of the OBS
integration keeps switching Program directly, which Studio Mode allows.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends

import core.events as events
import integrations.obs_ws as obs_ws
import routers.obs as obs
from routers._util import json_body
from security.deps import require_dm
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)
router = APIRouter(prefix='/ttrpg/producer/api')

PING_TTL_S = 45              # a console that stops pinging is gone
STUDIO_OFF_GRACE_S = 10      # reconnect window before Studio Mode is dropped
SWEEP_S = 15                 # self-re-arming reap interval while any console is open
PAUSE_KEY = 'obs_auto_cam_paused_by_producer'
SPECIALS_FRONT = ('party', 'map')
SPECIALS_BACK = ('pre', 'intermission', 'post')

_consoles = {}               # console_id -> last ping (time.monotonic())
_lock = threading.Lock()     # guards _consoles, _off_timer and _sweep_timer
_off_timer = None
_sweep_timer = None
_armed = {'key': None}       # shot key currently in Preview (by this router)


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _sfx():
    sid = obs._active_session_id()
    return f':s{sid}' if sid else ''


def _emit_state():
    try:
        events.emit('producer', {'kind': 'state'})
    except Exception:
        pass


# ── console registry ─────────────────────────────────────────────────────────
#
# _consoles, _off_timer and _sweep_timer are all guarded by _lock. The lock is
# held only around dict/timer bookkeeping — never around an OBS call or
# appsettingSet, and console_count() must never be called while already
# holding _lock (it takes the lock itself).

def _reap_locked(now):
    """Drop ping-expired consoles. Caller must hold _lock."""
    stale = [cid for cid, at in _consoles.items() if now - at > PING_TTL_S]
    for cid in stale:
        del _consoles[cid]
    return stale


def console_count():
    now = time.monotonic()
    with _lock:
        stale = _reap_locked(now)
        n = len(_consoles)
    if stale and n == 0:
        _schedule_off()
    return n


def producer_active():
    return console_count() > 0


def _studio(on):
    if not obs_ws.connected():
        return
    try:
        obs_ws.set_studio_mode(on)
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        log.info('Studio Mode %s failed: %s', 'on' if on else 'off', exc)
    try:
        obs_ws.set_meter_events(on)
    except Exception as exc:
        log.info('meter events %s failed: %s', on, exc)


def _off_if_idle():
    """The grace timer fired: reap once more and, only if nobody reconnected
    (pinged or reopened) in the meantime, actually put things back."""
    global _off_timer
    now = time.monotonic()
    with _lock:
        _off_timer = None
        _reap_locked(now)
        idle = not _consoles
    if not idle:
        return
    appsettingSet(PAUSE_KEY, '0')
    _armed['key'] = None
    _studio(False)
    _emit_state()


def _schedule_off():
    global _off_timer
    t = threading.Timer(STUDIO_OFF_GRACE_S, _off_if_idle)
    t.daemon = True
    with _lock:
        if _off_timer is not None:
            _off_timer.cancel()
        _off_timer = t
        t.start()


def _sweep():
    """Self-re-arming reap: notices a console that crashed without DELETE and
    stopped pinging, even if nobody else calls into this module meanwhile.
    Re-arms only while a console is still on record; console_count() itself
    schedules the Studio-Mode-off grace timer when a reap empties the set."""
    global _sweep_timer
    console_count()
    t = None
    with _lock:
        if _consoles:
            t = threading.Timer(SWEEP_S, _sweep)
            t.daemon = True
            _sweep_timer = t
        else:
            _sweep_timer = None
    if t is not None:
        t.start()


def open_console():
    global _off_timer, _sweep_timer
    cid = uuid.uuid4().hex[:12]
    now = time.monotonic()
    sweep_t = None
    with _lock:
        _consoles[cid] = now
        first = len(_consoles) == 1
        if _off_timer is not None:
            _off_timer.cancel()
            _off_timer = None
        if first:
            sweep_t = threading.Timer(SWEEP_S, _sweep)
            sweep_t.daemon = True
            _sweep_timer = sweep_t
    if sweep_t is not None:
        sweep_t.start()
    if first:
        appsettingSet(PAUSE_KEY, '1')
        _studio(True)
    if not (appsettingGet('producer_clock_start' + _sfx(), '') or '').strip():
        appsettingSet('producer_clock_start' + _sfx(), _now())
    _emit_state()
    return cid


def ping_console(cid):
    with _lock:
        if cid in _consoles:
            _consoles[cid] = time.monotonic()
            return True
    return False


def close_console(cid):
    with _lock:
        _consoles.pop(cid, None)
        last = not _consoles
    if last:
        _schedule_off()
    _emit_state()


# ── shots ────────────────────────────────────────────────────────────────────

def shots():
    """Every shot the console can arm, in tile order: party, map, the players
    and the DM (the number keys count these), then the show cards."""
    built = set(obs_ws.current_state().get('scenes') or [])
    out = []

    def special(key):
        scene = obs._cut_scene_name(key)
        out.append({'key': key, 'label': obs.CUT_TARGETS[key][1], 'scene': scene,
                    'kind': 'special', 'built': scene in built, 'character_id': None})

    for key in SPECIALS_FRONT:
        special(key)
    for char in obs._ordered_party():
        is_dm = char.character_id == obs.DM_TILE_ID
        scene = obs._scene_name_for(char)
        out.append({'key': 'dm' if is_dm else f'char:{char.character_id}',
                    'label': char.name, 'scene': scene,
                    'kind': 'dm' if is_dm else 'player', 'built': scene in built,
                    'character_id': char.character_id})
    for key in SPECIALS_BACK:
        special(key)
    return out


def shot(key):
    for s in shots():
        if s['key'] == key:
            return s
    return None


# ── state ────────────────────────────────────────────────────────────────────

def _markers():
    try:
        return json.loads(appsettingGet('producer_markers' + _sfx(), '') or '[]')
    except ValueError:
        return []


def _session_info():
    from models.ttrpg import tblSessions
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return None
    return {'id': sess.session_id, 'title': sess.title, 'number': sess.session_number}


def state_doc():
    snap = obs_ws.current_state()
    sfx = _sfx()
    return {
        'connected': obs_ws.connected(),
        'studio_mode': bool(snap.get('studio_mode')),
        'program': snap.get('current_scene', ''),
        'preview': snap.get('preview_scene', ''),
        'armed': _armed['key'],
        'shots': shots(),
        'transitions': [t['name'] for t in snap.get('transitions') or []],
        'transition': snap.get('current_transition', ''),
        'transition_ms': snap.get('transition_ms', 0),
        'recording': bool(snap.get('recording')),
        'streaming': bool(snap.get('streaming')),
        'record_timecode': snap.get('record_timecode', ''),
        'stream_timecode': snap.get('stream_timecode', ''),
        'last_switch': snap.get('last_switch'),
        'auto_cam': obs.auto_cam_setting(),
        'auto_cam_paused': (appsettingGet(PAUSE_KEY, '0') or '0') == '1',
        'countdown_until': appsettingGet('producer_countdown_until' + sfx, '') or '',
        'clock_start': appsettingGet('producer_clock_start' + sfx, '') or '',
        'markers': _markers(),
        'consoles': console_count(),
        'session': _session_info(),
    }


# ── routes ───────────────────────────────────────────────────────────────────

@router.post('/session')
def api_session_open(user=Depends(require_dm)):
    return {'ok': True, 'console_id': open_console(), 'consoles': console_count()}


@router.post('/session/ping')
def api_session_ping(data: dict = Depends(json_body), user=Depends(require_dm)):
    return {'ok': ping_console(str(data.get('console_id', ''))), 'consoles': console_count()}


@router.delete('/session/{console_id}')
def api_session_close(console_id: str, user=Depends(require_dm)):
    close_console(console_id)
    return {'ok': True, 'consoles': console_count()}


@router.get('/state')
def api_state(user=Depends(require_dm)):
    return state_doc()


@router.post('/auto-cam-pause')
def api_auto_cam_pause(data: dict = Depends(json_body), user=Depends(require_dm)):
    paused = bool(data.get('paused', True))
    appsettingSet(PAUSE_KEY, '1' if paused else '0')
    _emit_state()
    return {'ok': True, 'paused': paused}

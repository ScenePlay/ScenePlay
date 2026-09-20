"""Producer console API — the live surface a second person runs the stream
from (/ttrpg/producer, spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md).

Lifecycle: the first console to open turns OBS Studio Mode and the audio
meter stream on (auto-cam keeps running unless the producer pauses it from the
console); STUDIO_OFF_GRACE_S after the last console closes (or stops pinging)
everything is put back, including any pause. The rest of the OBS
integration keeps switching Program directly, which Studio Mode allows.
"""
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response

import core.events as events
import integrations.obs_ws as obs_ws
import routers.obs as obs
from routers._util import json_body
from security.deps import ApiError, require_dm
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)
router = APIRouter(prefix='/ttrpg/producer/api')

PING_TTL_S = 45              # a console that stops pinging is gone
STUDIO_OFF_GRACE_S = 10      # reconnect window before Studio Mode is dropped
SWEEP_S = 15                 # self-re-arming reap interval while any console is open
PAUSE_KEY = 'obs_auto_cam_paused_by_producer'
SPECIALS_FRONT = ('party', 'map')
SPECIALS_BACK = ('pre', 'intermission', 'post', 'black')
CLOCK_STALE_S = 6 * 3600     # a session clock older than this is last night's
SHOTS_TTL_S = 2.0            # shots() hits the DB; the console asks constantly
STATE_MARKERS = 30           # the state document carries the tail; GET /markers has them all
_TS = '%Y-%m-%d %H:%M:%S'

_consoles = {}               # console_id -> last ping (time.monotonic())
_lock = threading.Lock()     # guards _consoles, _off_timer, _sweep_timer and _sweep_gen
_off_timer = None
_sweep_timer = None
_sweep_gen = 0                # bumped each time a sweeper chain is (re)armed from
                               # open_console; a running _sweep() retires instead of
                               # re-arming once its generation is superseded, so a
                               # close-then-reopen inside SWEEP_S never leaves two chains
_armed = {'key': None}       # shot key currently in Preview (by this router)
_markers_lock = threading.Lock()  # serialises marker append and clear (read-append-save race)


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


# ── remote consoles (the portal's producer page, via relay_producer) ─────────
#
# Remote consoles count like local ones: while any is open, Studio Mode and
# the meter subscription stay on. relay_producer owns the number; it drops to
# zero when the GM socket goes down.

_remote = {'consoles': 0}


def set_remote_consoles(n):
    """Called by relay_producer on every presence change from the portal."""
    n = max(0, int(n or 0))
    before = _remote['consoles']
    _remote['consoles'] = n
    if before == 0 and n > 0:
        global _off_timer
        with _lock:
            if _off_timer is not None:
                _off_timer.cancel()
                _off_timer = None
            local = len(_consoles)
        if local == 0:
            _studio(True)
            started = appsettingGet('producer_clock_start' + _sfx(), '') or ''
            age = _secs_since(started)
            if age is None or age > CLOCK_STALE_S:
                appsettingSet('producer_clock_start' + _sfx(), _now())
    elif before > 0 and n == 0:
        if console_count() == 0:
            _schedule_off()
    _emit_state()


def remote_console_count():
    return _remote['consoles']


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
    n += _remote['consoles']
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
        idle = not _consoles and _remote['consoles'] == 0
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


def _sweep(gen):
    """Self-re-arming reap: notices a console that crashed without DELETE and
    stopped pinging, even if nobody else calls into this module meanwhile.
    Re-arms only while a console is still on record; console_count() itself
    schedules the Studio-Mode-off grace timer when a reap empties the set.

    `gen` pins this call to the sweeper chain that scheduled it. A chain that
    a close-then-reopen has superseded (open_console bumps _sweep_gen and
    arms a fresh chain) retires here instead of re-arming, even if its Timer
    fired anyway before the cancel() reached it — so exactly one chain is
    ever running."""
    global _sweep_timer
    with _lock:
        if gen != _sweep_gen:
            return
    console_count()
    t = None
    with _lock:
        if gen != _sweep_gen:
            return
        if _consoles:
            t = threading.Timer(SWEEP_S, _sweep, args=(gen,))
            t.daemon = True
            _sweep_timer = t
        else:
            _sweep_timer = None
    if t is not None:
        t.start()


def open_console():
    global _off_timer, _sweep_timer, _sweep_gen
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
            if _sweep_timer is not None:
                _sweep_timer.cancel()          # a still-pending chain from before this
            _sweep_gen += 1                    # reopen: retire it, start a fresh one
            sweep_t = threading.Timer(SWEEP_S, _sweep, args=(_sweep_gen,))
            sweep_t.daemon = True
            _sweep_timer = sweep_t
    if sweep_t is not None:
        sweep_t.start()
    if first:
        # Auto-cam keeps running while a console is open (Eric's call, 2026-09-15):
        # the producer can pause it with the console's toggle when they want the
        # shots to themselves; the pause is lifted again when the last console leaves.
        _studio(True)
    # The session clock belongs to THIS sitting: keep a start that a console
    # opened earlier tonight, replace one left over from a previous session
    # (nothing else ever clears it).
    started = appsettingGet('producer_clock_start' + _sfx(), '') or ''
    age = _secs_since(started)
    if age is None or age > CLOCK_STALE_S:
        appsettingSet('producer_clock_start' + _sfx(), _now())
    _emit_state()
    return cid


def reset_after_restart():
    """Boot: no console survives the process, so neither may the auto-cam
    pause this module owns. Without this a crash (or a plain restart) while a
    console was open would leave auto-cam switched off for good, with no
    console left to un-pause it."""
    with _lock:
        _consoles.clear()
    _armed['key'] = None
    appsettingSet(PAUSE_KEY, '0')


def _on_obs_connected():
    """OBS came back (its own restart, or ours): it has forgotten Studio Mode
    and the meter subscription. Re-assert whichever way the console registry
    says it should be — including turning Studio Mode back OFF when the
    console that asked for it is long gone. Runs on obs_ws's hook thread."""
    if console_count() > 0:
        obs_ws.set_studio_mode(True)
        obs_ws.set_meter_events(True)
    elif obs_ws.current_state().get('studio_mode'):
        obs_ws.set_studio_mode(False)


obs_ws.add_connected_hook(_on_obs_connected)


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

_shots_cache = {'at': 0.0, 'key': None, 'value': []}


def shots():
    """Every shot the console can arm, in tile order: party, map, the players
    and the DM (the number keys count these), then the show cards.

    Cached for SHOTS_TTL_S, keyed by OBS's scene list: every console polls
    state (and each snapshot resolves a target) several times a second, and
    the party query behind this is the only DB work on that path. A scene
    built or renamed in OBS changes the key and busts the cache at once; a
    party edit shows up within the TTL."""
    built = tuple(obs_ws.current_state().get('scenes') or [])
    now = time.monotonic()
    cached = _shots_cache
    if cached['key'] == built and (now - cached['at']) < SHOTS_TTL_S:
        return [dict(s) for s in cached['value']]
    out = _build_shots(set(built))
    _shots_cache.update(at=now, key=built, value=out)
    return [dict(s) for s in out]


def _invalidate_shots():
    _shots_cache['at'] = 0.0


# ── closeup scenes ───────────────────────────────────────────────────────────

def build_closeups():
    """One OBS scene per on-stream member, named exactly as the console's
    shot (`Player - Carl`, `DM - Jankis`), holding that member's party-scene
    inputs full-frame: the cam source and, when they have one, the overlay
    (name strip / stat card). The inputs are SHARED with the party scene —
    OBS lets one input live in several scenes — so no second feed is opened.
    Members without a tile in the party scene yet are skipped (run Build).
    Raises ObsUnavailable / ObsRejected like the rest of the OBS surface."""
    snap = obs_ws.current_state()
    w, h = snap.get('base_width') or 1920, snap.get('base_height') or 1080
    full = {'x': 0, 'y': 0, 'w': w, 'h': h}
    party = obs.party_scene_name()
    party_items = obs_ws.scene_items(party)
    off_canvas = {'x': int(w) + 100, 'y': 0, 'w': 320, 'h': 180}
    built, skipped = [], []
    for char in obs._ordered_party():
        if char.character_id == obs.PRODUCER_TILE_ID:
            continue                      # no closeup: the producer lives on the grid only
        cam = obs._source_name_for(char)
        if cam not in party_items:
            skipped.append(char.name)
            continue
        scene = obs._scene_name_for(char)
        obs_ws.ensure_scene(scene)
        for source in (cam, obs._overlay_source_name_for(char)):
            if source not in party_items:
                continue
            item_id = obs_ws.ensure_item(scene, source)
            obs_ws.place_item(scene, item_id, full)
            obs_ws.set_item_enabled(scene, item_id, True)
        # Carry the table's sound into the closeup exactly as Build does for
        # the map and show cards: the party scene nested off-canvas — heard,
        # never seen — so a closeup silences nobody.
        audio = obs_ws.ensure_nested_scene(scene, party)
        if audio is not None:
            obs_ws.place_item(scene, audio, off_canvas)
            obs_ws.set_item_enabled(scene, audio, True)
        built.append(scene)
    _invalidate_shots()
    _emit_state()
    return {'built': built, 'skipped': skipped}


# Hotkeys mirror the Broadcast page: 1-9 are the tiles in party order (the
# DM rides along in that order), 0 is the whole party, B the battle map, I the
# intermission card. Pre/post are click-only.
# P = pre-show (intro), O = post-show (outro): letters no other console key uses
SPECIAL_HOTKEYS = {'party': '0', 'map': 'B', 'intermission': 'I', 'pre': 'P', 'post': 'O', 'black': 'F'}


def _build_shots(built):
    out = []

    def special(key):
        scene = obs._cut_scene_name(key)
        out.append({'key': key, 'label': obs.CUT_TARGETS[key][1], 'scene': scene,
                    'kind': 'special', 'built': scene in built, 'character_id': None,
                    'hotkey': SPECIAL_HOTKEYS.get(key, '')})

    for key in SPECIALS_FRONT:
        special(key)
    # The producer's tile (last on the grid while barged in) is not a shot:
    # their presence is the party screen only, so no closeup and no key.
    party = [c for c in obs._ordered_party() if c.character_id != obs.PRODUCER_TILE_ID]
    for n, char in enumerate(party, start=1):
        is_dm = char.character_id == obs.DM_TILE_ID
        scene = obs._scene_name_for(char)
        out.append({'key': 'dm' if is_dm else f'char:{char.character_id}',
                    'label': char.name, 'scene': scene,
                    'kind': 'dm' if is_dm else 'player', 'built': scene in built,
                    'character_id': char.character_id,
                    'hotkey': str(n) if n <= 9 else ''})
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
        rows = json.loads(appsettingGet('producer_markers' + _sfx(), '') or '[]')
    except ValueError:
        return []
    return rows if isinstance(rows, list) else []


def _obs_info():
    """Enough for the console to say WHY OBS is not connected and offer the
    fix: switched off, still connecting, refused the password, unsupported.
    Never the password; host:port only."""
    host = (appsettingGet('obs_host', '') or '').strip() or obs_ws.DEFAULT_HOST
    port = (appsettingGet('obs_port', '') or '').strip() or str(obs_ws.DEFAULT_PORT)
    err = obs_ws.last_error() or ''
    return {'enabled': (appsettingGet('obs_enabled', '0') or '0') == '1',
            'state': obs_ws.state(),
            'error': err.split('|', 2)[-1] if err else '',
            'target': f'{host}:{port}'}


def _session_scenes():
    """The ScenePlay scenes the console offers: exactly what the DM's session
    and battle-map screens list — the active session's campaign, enabled
    scenes only, in the DM's order — each with its OBS scene link."""
    from models.scenes import tblscenes
    from models.ttrpg import tblSessions
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess or sess.campaign_id is None:
        return []
    links = _scene_links()
    rows = (tblscenes.query.filter_by(campaign_id=sess.campaign_id, active=1)
            .order_by(tblscenes.orderBy).all())
    return [{'scene_ID': r.scene_ID, 'sceneName': r.sceneName,
             'obs_scene': links.get(str(r.scene_ID))} for r in rows]


def _scene_links():
    """{ScenePlay scene_ID (str): OBS scene name} — the DM screen's links,
    followed by /activatescenes/ when obs_scene_link is on."""
    from models.ttrpg import tblObsSceneMap
    return {str(r.entity_id): r.scene_name
            for r in tblObsSceneMap.query.filter_by(entity_type='scene').all() if r.scene_name}


def _session_info():
    from models.ttrpg import tblSessions
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return None
    return {'id': sess.session_id, 'title': sess.title, 'number': sess.session_number}


def _secs_since(text):
    """Whole seconds since a stored local timestamp, or None when it is unset
    or unparsable. Both clocks are computed HERE: the stored strings are local
    time with no offset, so a browser in another timezone (or with a skewed
    clock) cannot parse them correctly on its own."""
    try:
        return int((datetime.now() - datetime.strptime((text or '').strip(), _TS)).total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None


def state_doc():
    snap = obs_ws.current_state()
    sfx = _sfx()
    countdown_until = appsettingGet('producer_countdown_until' + sfx, '') or ''
    clock_start = appsettingGet('producer_clock_start' + sfx, '') or ''
    elapsed = _secs_since(clock_start)
    left = _secs_since(countdown_until)
    return {
        'connected': obs_ws.connected(),
        'studio_mode': bool(snap.get('studio_mode')),
        'program': snap.get('current_scene', ''),
        'preview': snap.get('preview_scene', ''),
        'armed': _armed['key'],
        'shots': shots(),
        'transitions': [t['name'] for t in snap.get('transitions') or []],
        'transitions_fixed': [t['name'] for t in snap.get('transitions') or [] if t.get('fixed')],
        'transition_fixed': _saved_transition(snap)[0] in {t['name'] for t in snap.get('transitions') or [] if t.get('fixed')},
        'transition': _saved_transition(snap)[0],
        'transition_ms': _saved_transition(snap)[1],
        'recording': bool(snap.get('recording')),
        'streaming': bool(snap.get('streaming')),
        'record_timecode': snap.get('record_timecode', ''),
        'stream_timecode': snap.get('stream_timecode', ''),
        'last_switch': snap.get('last_switch'),
        'auto_cam': obs.auto_cam_setting(),
        # The console's AUTO / 2D / 3D button is the battle map's: same
        # setting, same endpoint, painted from here so a change made on either
        # page shows on both.
        'map_mode': obs.map_mode(),
        'featured_id': obs.featured_id(),
        'obs': _obs_info(),
        'scene_links': _scene_links(),
        'scenes': _session_scenes(),
        'scene_links_live': obs.scene_links_live(),
        'auto_cam_paused': (appsettingGet(PAUSE_KEY, '0') or '0') == '1',
        'countdown_until': countdown_until,
        'clock_start': clock_start,
        # ...and the same two clocks already resolved to seconds, so the
        # console only has to add the time since it fetched this document.
        'clock_elapsed_s': None if elapsed is None else max(0, elapsed),
        'countdown_left_s': None if left is None else -left,
        'markers': _markers()[-STATE_MARKERS:],
        'consoles': console_count(),
        'session': _session_info(),
        'producer': producer_info(),
        # tiles still rendering at a size from an earlier member count: a
        # reflow never resizes a running camera (that reload is what made
        # barge-in stutter); Rebuild does, at a break
        'stale_tiles': obs.stale_render_count(),
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
    return set_auto_cam_pause(bool(data.get('paused', True)))


def set_auto_cam_pause(paused):
    appsettingSet(PAUSE_KEY, '1' if paused else '0')
    _emit_state()
    return {'ok': True, 'paused': bool(paused)}


# ── switching ────────────────────────────────────────────────────────────────

def _obs_error(exc):
    if isinstance(exc, obs_ws.ObsRejected):
        return f'OBS refused: {exc.comment or exc}'
    return 'Lost the OBS connection.'


@router.post('/arm')
def api_arm(data: dict = Depends(json_body), user=Depends(require_dm)):
    return arm(str(data.get('key', '') or ''))


def arm(key):
    """Put a shot in Preview (empty key: forget the armed shot). Shared by
    the local console endpoint and remote producer commands."""
    if not key:
        # Escape on the console: forget what was armed WITHOUT touching OBS's
        # preview — the operator is clearing their own intent, not the shot
        # the next Take would put on air.
        _armed['key'] = None
        _emit_state()
        return {'ok': True, 'armed': None}
    s = shot(key)
    if not s:
        raise ApiError(400, f'Unknown shot {key!r}', code='bad_shot')
    if not s['built'] and key == 'black' and obs_ws.connected():
        # The blank screen is an empty scene: make it on the spot rather than
        # sending the producer to the Broadcast page for nothing.
        try:
            obs_ws.ensure_scene(s['scene'])
            obs_ws.scene_list(refresh=True)
        except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
            return {'ok': False, 'error': _obs_error(exc)}
        _invalidate_shots()
        s = shot(key) or s
    if not s['built']:
        return {'ok': False, 'error': f"{s['label']}: scene not built yet — run Build on the Broadcast page."}
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    try:
        obs_ws.set_preview_scene(s['scene'])
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    _armed['key'] = key
    _emit_state()
    return {'ok': True, 'armed': key, 'scene': s['scene']}


def _saved_transition(snap=None):
    """The Broadcast page's transition (obs_transition / obs_transition_ms)
    when the DM saved one, else whatever OBS has selected. The console's
    dropdown starts here and a Take that names nothing uses it."""
    snap = snap or obs_ws.current_state()
    name = (appsettingGet('obs_transition', '') or '').strip() or snap.get('current_transition', '')
    raw = (appsettingGet('obs_transition_ms', '') or '').strip()
    try:
        ms = int(raw) if raw else int(snap.get('transition_ms') or 300)
    except (TypeError, ValueError):
        ms = 300
    return name, ms


def _take(transition, ms):
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    scene = obs_ws.preview_scene()
    program = obs_ws.current_state().get('current_scene', '')
    if _armed['key'] is None and (not scene or scene == program):
        return {'ok': False, 'error': 'Nothing armed — arm a shot first (click a tile or press its key), then Take or Auto.'}
    try:
        if transition:
            obs_ws.set_transition(transition, ms)
        obs_ws.trigger_transition()
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    key = _armed['key'] or ''
    _armed['key'] = None
    obs._emit('cut', target=key, scene=scene, by='producer')
    out = {'ok': True, 'scene': scene, 'transition': transition}
    warning = _feature_after_take(key)
    if warning:
        out['warning'] = warning
    _emit_state()
    return out


def _feature_after_take(key):
    """A player (or DM) closeup taken here also features them in the party
    scene — off-air, since program is now the closeup — so the Broadcast
    page's turn state and the party layout stay in step with the stream.
    Never fails the take: returns a warning text or ''."""
    s = shot(key) if key else None
    if not s or s['kind'] not in ('player', 'dm'):
        return ''
    try:
        obs._sync_party_scene(featured_id=s['character_id'])
        obs._set_featured(s['character_id'])
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return f"Cut done, but featuring {s['label']} in the party scene failed: {getattr(exc, 'comment', '') or exc}"
    return ''


def _ms(data, default=None):
    try:
        v = int(data.get('ms'))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


TRANSITION_MS_MAX = 10000


def set_transition_pref(name, ms):
    """The Take fade, chosen on either console and SAVED: the same
    obs_transition / obs_transition_ms the Broadcast page writes, so every
    Take, the Broadcast page and the scene-link cuts agree. Reverses the
    2026-09-15 'no picker' decision (Eric, 2026-09-19)."""
    name = re.sub(r'[\x00-\x1f]', '', str(name or '')).strip()[:64]
    snap = obs_ws.current_state()
    known = {t['name']: bool(t.get('fixed')) for t in snap.get('transitions') or []}
    if not name:
        raise ApiError(400, 'transition name required', code='bad_request')
    if known and name not in known:
        raise ApiError(400, f'OBS has no transition named {name!r}', code='bad_request')
    try:
        ms = int(ms if ms is not None else 0)
    except (TypeError, ValueError):
        raise ApiError(400, 'ms must be an integer', code='bad_request')
    ms = max(0, min(TRANSITION_MS_MAX, ms))
    fixed = bool(known.get(name))
    appsettingSet('obs_transition', name)
    if fixed or ms <= 0:
        # Cut takes no duration: keep the saved fade length untouched so
        # switching back to Fade brings the last length with it (Eric, 2026-09-19).
        # A zero-length fade keeps it too: 0 ms is a cut wearing a fade's name,
        # and the console used to send one whenever its length box showed "Cut".
        ms = _saved_transition(snap)[1]
    else:
        appsettingSet('obs_transition_ms', str(ms))
    _emit_state()
    return {'ok': True, 'transition': name, 'transition_ms': ms, 'fixed': fixed}


@router.post('/transition')
def api_transition(data: dict = Depends(json_body), user=Depends(require_dm)):
    return set_transition_pref(data.get('name'), data.get('ms'))


@router.post('/take')
def api_take(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Preview -> Program with the Broadcast page's saved transition and
    duration (else OBS's current one). The console sends an empty body: the
    fade is set once, on the Broadcast page, and every Take uses it. A body
    may still name a transition and ms (remotes, scripts)."""
    return take(data)


def take(data=None):
    """Preview -> Program with the saved transition (a body may override)."""
    data = data or {}
    default_name, default_ms = _saved_transition()
    name = (str(data.get('transition') or '')).strip() or default_name or None
    return _take(name, _ms(data, default_ms))


@router.post('/obs/connect')
def api_obs_connect(user=Depends(require_dm)):
    """Connect (or reconnect) to OBS from the console: switches OBS control
    on when it is off — the same path as the Broadcast page's Enable — and
    otherwise drops and redials with the saved host/port/password."""
    if (appsettingGet('obs_enabled', '0') or '0') != '1':
        out = obs.enable_obs()
        _emit_state()
        return out
    obs_ws.restart()
    _emit_state()
    return {'ok': True, 'enabled': True, 'message': 'Reconnecting to OBS.'}


@router.post('/spotlight')
def api_spotlight(data: dict = Depends(json_body), user=Depends(require_dm)):
    """The Broadcast page's spotlight, from the console: {'key': 'char:N'|'dm'}
    re-lays-out the party scene with that tile enlarged (the rest shrink),
    {'key': ''} evens the table out again. A setting, never a cut: the party
    scene is ARRANGED and Program stays where it is — a closeup or the
    post-show card must not be yanked off air because the operator lined up
    the next spotlight; the arrangement goes live with the next Take or cut
    to the party scene. (2026-09-19 briefly made it cut when Program was
    elsewhere; reversed 2026-09-20, Eric.)"""
    return spotlight(str(data.get('key', '') or ''))


def spotlight(key):
    if key:
        s = shot(key)
        if not s or s['kind'] == 'special':
            raise ApiError(400, f'Not a player shot: {key!r}', code='bad_shot')
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    try:
        if key:
            obs._sync_party_scene(featured_id=s['character_id'])
            obs._set_featured(s['character_id'])
            obs._emit('feature', character_id=s['character_id'])
        else:
            obs._sync_party_scene(featured_id=None)
            obs._set_featured(None)
            obs._cancel_return()
            obs._emit('group')
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    _emit_state()
    return {'ok': True, 'featured': key or None, 'featured_id': s['character_id'] if key else None}


@router.post('/build-closeups')
def api_build_closeups(user=Depends(require_dm)):
    """Build (or repair) the per-member closeup scenes the player shots arm."""
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    try:
        result = build_closeups()
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    return {'ok': True, **result}


# ── the producer on the stream (camera link, barge-in, name) ─────────────────
#
# Spec: docs/superpowers/specs/2026-09-18-producer-camera-and-barge-design.md.
# The producer's camera link joins the table's VDO.ninja room (their live
# link: every mic, camera and the music). Barging in puts their tile LAST on
# the party grid; leaving removes it, and with it their sound from the stream.

def producer_info():
    tile = obs.producer_tile()
    return {'tile_id': obs.PRODUCER_TILE_ID, 'on_screen': obs.producer_on_screen(),
            'name': tile.name, 'icon': obs.producer_icon(), 'icons': list(obs.PRODUCER_ICONS),
            'push_url': tile.video_push_url(),
            'feed': obs._feed_state(tile, obs._presence())}


def set_barge(on):
    on = bool(on)
    appsettingSet('obs_producer_on_screen', '1' if on else '0')
    tile = obs.producer_tile()                # mints the link on first use
    warnings = []
    if obs_ws.connected():
        try:
            if on:
                # Source first, parked off-canvas, then the reflow: the browser
                # source's start-up must not land on top of the animation.
                warnings.extend(obs.stage_tile(tile))
            res = obs._sync_party_scene(featured_id=obs.featured_id())
            warnings = list((res or {}).get('warnings') or [])
            obs.refresh_tiles()
        except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
            warnings.append(_obs_error(exc))
    _invalidate_shots()
    obs._emit('build')
    _emit_state()
    return {'ok': True, 'on_screen': on, 'warnings': warnings}


def set_profile(name, icon=None):
    name = re.sub(r'[\x00-\x1f]', '', str(name or '')).strip()[:60]
    appsettingSet('obs_producer_name', name)
    if icon is not None:
        icon = str(icon).strip()
        appsettingSet('obs_producer_icon', icon if icon in obs.PRODUCER_ICONS else '')
    # The tile's name strip and card poll their state, so the new name lands
    # on the next poll; a re-layout is only needed for the scene name itself.
    _invalidate_shots()
    obs._emit('build')
    _emit_state()
    return {'ok': True, 'name': obs.producer_name(), 'icon': obs.producer_icon()}


@router.post('/barge')
def api_barge(data: dict = Depends(json_body), user=Depends(require_dm)):
    return set_barge(data.get('on', True))


@router.post('/profile')
def api_profile(data: dict = Depends(json_body), user=Depends(require_dm)):
    return set_profile(data.get('name', ''), data.get('icon'))


# ── clocks and markers ───────────────────────────────────────────────────────

MARKERS_MAX = 200


@router.post('/countdown')
def api_countdown(data: dict = Depends(json_body), user=Depends(require_dm)):
    """{'seconds': n} counts down from now; {'until': 'YYYY-MM-DD HH:MM:SS'}
    sets an absolute end; {'clear': true} removes it."""
    return set_countdown(data)


def set_countdown(data):
    from datetime import timedelta
    key = 'producer_countdown_until' + _sfx()
    if data.get('clear'):
        appsettingSet(key, '')
        _emit_state()
        return {'ok': True, 'until': ''}
    until = None
    if data.get('until'):
        try:
            until = datetime.strptime(str(data['until']).strip(), _TS)
        except ValueError:
            raise ApiError(400, 'until must be YYYY-MM-DD HH:MM:SS', code='bad_request')
    elif data.get('seconds') is not None:
        try:
            secs = int(data['seconds'])
        except (TypeError, ValueError):
            raise ApiError(400, 'seconds must be an integer', code='bad_request')
        if secs <= 0:
            raise ApiError(400, 'seconds must be positive', code='bad_request')
        until = datetime.now() + timedelta(seconds=secs)
    if until is None:
        raise ApiError(400, 'seconds, until or clear required', code='bad_request')
    text = until.strftime(_TS)
    appsettingSet(key, text)
    _emit_state()
    return {'ok': True, 'until': text}


@router.post('/clock/reset')
def api_clock_reset(user=Depends(require_dm)):
    return clock_reset()


def clock_reset():
    now = _now()
    appsettingSet('producer_clock_start' + _sfx(), now)
    _emit_state()
    return {'ok': True, 'clock_start': now}


def _save_markers(rows):
    appsettingSet('producer_markers' + _sfx(), json.dumps(rows[-MARKERS_MAX:]))


@router.post('/marker')
def api_marker(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Stamp the moment: a chapter in the recording when one is running, and
    always a row in the session's marker list (for the edit later)."""
    return add_marker(data.get('note', ''))


def add_marker(note):
    note = (str(note or '')).strip()[:200] or 'Marker'
    snap = obs_ws.current_state()
    recording = bool(snap.get('recording'))
    marker = {'at': _now(), 'timecode': snap.get('record_timecode', '') if recording else '',
              'note': note, 'recording': recording, 'chapter': False}
    warning = ''
    if recording and obs_ws.connected():
        try:
            obs_ws.record_chapter(note)
            marker['chapter'] = True
        except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
            warning = f'Marker saved, but OBS did not add a chapter: {getattr(exc, "comment", "") or exc}'
    with _markers_lock:
        rows = _markers()
        rows.append(marker)
        _save_markers(rows)
    _emit_state()
    out = {'ok': True, 'marker': marker}
    if warning:
        out['warning'] = warning
    return out


@router.get('/markers')
def api_markers(user=Depends(require_dm)):
    return {'markers': _markers()}


@router.delete('/markers')
def api_markers_clear(user=Depends(require_dm)):
    return clear_markers()


def clear_markers():
    with _markers_lock:
        _save_markers([])
    _emit_state()
    return {'ok': True}


# ── multiview ────────────────────────────────────────────────────────────────

SNAP_WIDTH = 320


def _snap_source(target):
    snap = obs_ws.current_state()
    if target == 'program':
        return snap.get('current_scene', '')
    if target == 'preview':
        return snap.get('preview_scene', '')
    s = shot(target)
    if s is None:
        raise ApiError(404, f'Unknown snapshot target {target!r}', code='not_found')
    return s['scene']


@router.get('/snap/{target}')
def api_snap(target: str, user=Depends(require_dm)):
    """One JPEG frame of Program, Preview or a shot's scene. 204 (no body)
    whenever OBS cannot give one — the console keeps the last frame."""
    source = _snap_source(target)
    headers = {'Cache-Control': 'no-store'}
    if not source or not obs_ws.connected():
        return Response(status_code=204, headers=headers)
    try:
        data = obs_ws.screenshot(source, width=SNAP_WIDTH)
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected):
        data = b''
    if not data:
        return Response(status_code=204, headers=headers)
    return Response(content=data, media_type='image/jpeg', headers=headers)


@router.get('/levels')
def api_levels(user=Depends(require_dm)):
    lv, at = obs_ws.levels()
    age_ms = int((time.monotonic() - at) * 1000) if at else 0
    return {'levels': lv, 'age_ms': max(0, age_ms)}

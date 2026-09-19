"""Remote producer console — the local half.

The portal (../ScenePlayRemote) shows the producer console to DM logins. It
never touches OBS, the DB or the players: everything it shows was pushed from
here, and everything it does comes back as a STAGED COMMAND that this module
executes through the same functions the local console uses, then acks.
Spec: docs/superpowers/specs/2026-09-18-remote-producer-console-design.md

Up (over relay_ws, fire-and-forget):
  producer_state  — the console's state document + audio rows + levels,
                    on every local change and every HEARTBEAT_S while a
                    remote console is open.
  producer_frame  — one JPEG (base64) of Program / Preview (FRAME_MON_S) or
                    a shot tile (FRAME_TILE_S), only while a remote console
                    is open. Nothing is queued: a frame that fails is dropped.
Down (relay_ws events, the hello replay, the /sync poll):
  producer_presence {consoles}   → set_presence()
  producer_command  <row>        → enqueue(); executed in order on one
                                   worker thread, acked producer_ack.
Every entry point swallows its own failures: this feature must never break
the relay link, OBS control or local playback.
"""
import base64
import json
import logging
import queue
import threading
import time
from contextlib import nullcontext

import core.events as events

log = logging.getLogger(__name__)

HEARTBEAT_S = 5.0
FRAME_MON_S = 1.0
FRAME_TILE_S = 5.0
FRAME_WIDTH = 320
TTL_DEFAULT_S = {'arm': 5, 'take': 5}
TTL_OTHER_S = 30
LEDGER_KEY = 'relay_applied_producer_ids'
LEDGER_SESSION_KEY = 'relay_applied_producer_session'
LEDGER_SIZE = 200
STATE_TOPICS = ('producer', 'obs', 'scene', 'queue', 'nowplaying')

_app = None
_stop = threading.Event()
_wake = threading.Event()          # something to push (state dirty / presence)
_dirty = threading.Event()         # a state push is due before the heartbeat
_push_thread = None
_cmd_thread = None
_cmd_queue = queue.Queue()
_ledger_lock = threading.Lock()


# ── lifecycle ────────────────────────────────────────────────────────────────

def start(app):
    """Idempotent. Threads idle until a remote console opens."""
    global _app, _push_thread, _cmd_thread
    _app = app
    _stop.clear()
    events.add_listener(_on_event)
    if _push_thread is None or not _push_thread.is_alive():
        _push_thread = threading.Thread(target=_push_loop, daemon=True, name='relay-producer-push')
        _push_thread.start()
    if _cmd_thread is None or not _cmd_thread.is_alive():
        _cmd_thread = threading.Thread(target=_cmd_loop, daemon=True, name='relay-producer-cmd')
        _cmd_thread.start()


def stop():
    _stop.set()
    _wake.set()
    events.remove_listener(_on_event)
    _cmd_queue.put(None)
    try:
        set_presence(0)
    except Exception:
        pass


def _ctx():
    if _app is not None and hasattr(_app, 'app_context'):
        return _app.app_context()
    return nullcontext()


def _producer():
    import routers.producer as producer
    return producer


# ── presence ─────────────────────────────────────────────────────────────────

def set_presence(n):
    """Remote console count from the portal (presence event / hello)."""
    try:
        with _ctx():
            _producer().set_remote_consoles(n)
    except Exception as exc:
        log.info('set_remote_consoles failed: %s', exc)
    _dirty.set()
    _wake.set()


def remote_consoles():
    try:
        return _producer().remote_console_count()
    except Exception:
        return 0


def link_up(hello):
    """Hello replay: console count first (so frames start), then any
    commands staged while the socket was down."""
    set_presence(int(hello.get('producer_consoles') or 0))
    for row in hello.get('pending_producer_commands') or []:
        enqueue(row)


def link_down():
    set_presence(0)


# ── state push ───────────────────────────────────────────────────────────────

def _on_event(topic, payload):
    if topic in STATE_TOPICS and remote_consoles() > 0:
        _dirty.set()
        _wake.set()


def build_state():
    """The local console's document plus what the portal cannot fetch for
    itself: the OBS audio rows (mutes, faders), meter levels and the room
    volume. Levels are included at heartbeat rate — good enough for a remote
    strip; the local console keeps its 4 Hz poll."""
    p = _producer()
    import integrations.obs_ws as obs_ws
    doc = p.state_doc()
    rows, music_db = [], 0
    try:
        from routers.obs import _mapping_rows, _ordered_party, _volume_db
        for r in _mapping_rows(_ordered_party(include_offstage=True), obs_ws.current_state()):
            if r.get('on_stream'):
                rows.append({'name': r.get('name'), 'character_id': r.get('character_id'),
                             'muted': bool(r.get('muted')), 'volume_db': float(r.get('volume_db') or 0)})
        music_db = float(_volume_db('music') or 0)
    except Exception as exc:
        log.debug('audio rows unavailable: %s', exc)
    try:
        lv, _at = obs_ws.levels()
    except Exception:
        lv = {}
    try:
        from extensions import currentvolume
        vol = int(currentvolume() or 0)
    except Exception:
        vol = 0
    try:
        from routers.public import nowplaying
        np_doc = nowplaying()
    except Exception:
        np_doc = None
    doc.update({'audio_rows': rows, 'music_volume_db': music_db, 'levels': lv,
                'music_volume': vol, 'now_playing': np_doc, 'pushed_at': time.time()})
    return doc


def push_state():
    """One state frame up the socket. Returns True when sent."""
    import integrations.relay_ws as rw
    if not rw.connected():
        return False
    try:
        with _ctx():
            doc = build_state()
        rw.send_event('producer_state', doc)
        return True
    except Exception as exc:
        log.debug('producer_state push failed: %s', exc)
        return False


def push_frame(target):
    """One JPEG of a snapshot target. Returns True when sent."""
    import integrations.relay_ws as rw
    import integrations.obs_ws as obs_ws
    if not rw.connected() or not obs_ws.connected():
        return False
    try:
        with _ctx():
            source = _producer()._snap_source(target)
        if not source:
            return False
        data = obs_ws.screenshot(source, width=FRAME_WIDTH)
        if not data:
            return False
        rw.send_event('producer_frame', {
            'target': target, 'jpeg_b64': base64.b64encode(data).decode('ascii'),
            'ts': time.time()})
        return True
    except Exception as exc:
        log.debug('producer_frame %s failed: %s', target, exc)
        return False


def _shot_keys():
    try:
        with _ctx():
            return [s['key'] for s in _producer().shots() if s.get('built')]
    except Exception:
        return []


def _push_loop():
    last_state = 0.0
    last_mon = 0.0
    last_tile = 0.0
    tile_i = 0
    while not _stop.is_set():
        if remote_consoles() <= 0:
            _wake.wait(HEARTBEAT_S)
            _wake.clear()
            if remote_consoles() <= 0:
                continue
        now = time.monotonic()
        if _dirty.is_set() or now - last_state >= HEARTBEAT_S:
            _dirty.clear()
            if push_state():
                last_state = time.monotonic()
            else:
                last_state = time.monotonic() - HEARTBEAT_S + 1.0   # retry in a second
        now = time.monotonic()
        if now - last_mon >= FRAME_MON_S:
            last_mon = now
            push_frame('program')
            push_frame('preview')
        if now - last_tile >= FRAME_TILE_S:
            keys = _shot_keys()
            if keys:
                # one tile per FRAME_TILE_S / len(keys): every tile refreshes
                # once per FRAME_TILE_S without a burst
                last_tile = now - FRAME_TILE_S + FRAME_TILE_S / max(1, len(keys))
                push_frame(keys[tile_i % len(keys)])
                tile_i += 1
            else:
                last_tile = now
        _wake.wait(0.25)
        _wake.clear()


# ── commands ─────────────────────────────────────────────────────────────────

def enqueue(row):
    if isinstance(row, dict) and row.get('id') is not None:
        _cmd_queue.put(row)


def _cmd_loop():
    while not _stop.is_set():
        row = _cmd_queue.get()
        if row is None:
            break
        try:
            cid, status, error = execute(row)
            _ack(cid, status, error, row.get('session_id'))
        except Exception as exc:
            log.warning('producer command %s crashed: %s', row.get('id'), exc)


def _ledger_load(session_id):
    from sql import appsettingGet, appsettingSet
    if (appsettingGet(LEDGER_SESSION_KEY, '') or '') != str(session_id or ''):
        appsettingSet(LEDGER_SESSION_KEY, str(session_id or ''))
        appsettingSet(LEDGER_KEY, '[]')
        return set()
    try:
        return set(int(i) for i in json.loads(appsettingGet(LEDGER_KEY, '[]') or '[]'))
    except (ValueError, TypeError):
        return set()


def _ledger_add(ledger, cid):
    from sql import appsettingSet
    ledger.add(int(cid))
    try:
        appsettingSet(LEDGER_KEY, json.dumps(sorted(ledger)[-LEDGER_SIZE:]))
    except Exception as exc:
        log.warning('producer ledger save failed: %s', exc)


def ttl_for(cmd, row):
    try:
        ttl = float(row.get('ttl_s'))
        if ttl > 0:
            return ttl
    except (TypeError, ValueError):
        pass
    return float(TTL_DEFAULT_S.get(cmd, TTL_OTHER_S))


def execute(row):
    """Run one staged command. Returns (id, status, error) with status
    'applied' | 'rejected' | 'expired'. Idempotent per command id within a
    relay session (the ledger), so a replayed row is re-acked, never re-run."""
    cid = row.get('id')
    cmd = str(row.get('cmd') or '')
    args = row.get('args')
    if isinstance(args, str):
        try:
            args = json.loads(args or '{}')
        except (ValueError, TypeError):
            args = {}
    args = args if isinstance(args, dict) else {}
    with _ledger_lock:
        ledger = _ledger_load(row.get('session_id'))
        if cid in ledger:
            return cid, 'applied', ''
        _ledger_add(ledger, cid)
    try:
        age = float(row.get('age_s') or 0)
    except (TypeError, ValueError):
        age = 0.0
    if age > ttl_for(cmd, row):
        return cid, 'expired', f'{cmd} arrived {age:.0f}s late'
    try:
        with _ctx():
            out = _dispatch(cmd, args)
    except Exception as exc:
        detail = getattr(exc, 'detail', None) or getattr(exc, 'comment', None) or str(exc)
        return cid, 'rejected', str(detail)[:300]
    if out is None:
        return cid, 'rejected', f'unknown command {cmd!r}'
    if isinstance(out, dict) and out.get('ok') is False:
        return cid, 'rejected', str(out.get('error') or 'refused')[:300]
    return cid, 'applied', ''


def _plain(resp):
    """Endpoint functions may answer with a JSONResponse: read its body."""
    body = getattr(resp, 'body', None)
    if body is not None:
        try:
            return json.loads(body)
        except (ValueError, TypeError):
            return {'ok': False, 'error': 'bad response'}
    return resp


def _dispatch(cmd, args):
    p = _producer()
    if cmd == 'arm':
        return p.arm(str(args.get('key') or ''))
    if cmd == 'take':
        return p.take(args)
    if cmd == 'spotlight':
        return p.spotlight(str(args.get('key') or ''))
    if cmd == 'auto_cam_pause':
        return p.set_auto_cam_pause(bool(args.get('paused', True)))
    if cmd == 'countdown':
        return p.set_countdown(args)
    if cmd == 'marker':
        return p.add_marker(args.get('note') or '')
    if cmd == 'clock_reset':
        return p.clock_reset()
    if cmd == 'markers_clear':
        return p.clear_markers()
    if cmd == 'barge':
        return p.set_barge(bool(args.get('on', True)))
    if cmd == 'producer_profile':
        return p.set_profile(args.get('name') or '', args.get('icon'))
    if cmd == 'transition':
        return p.set_transition_pref(args.get('name'), args.get('ms'))
    if cmd == 'map_view':
        from routers.obs import api_map_mode
        return _plain(api_map_mode(args, None))
    if cmd == 'mute':
        from routers.obs import api_mute
        return _plain(api_mute(args, None))
    if cmd == 'fader':
        from routers.obs import api_volume
        return _plain(api_volume(args, None))
    if cmd == 'activate_scene':
        from routers.public import activatescene
        return activatescene(id=str(args.get('scene_id')))
    if cmd == 'skip':
        from routers.public import nextsong
        nextsong()
        return {'ok': True}
    if cmd == 'kill':
        from routers.public import killqueue
        killqueue()
        return {'ok': True}
    if cmd == 'lights_off':
        from routers.public import lights_off
        lights_off()
        return {'ok': True}
    if cmd == 'music_toggle':
        from media.mpv_ipc import mpv_command
        mpv_command('music', 'cycle pause')
        return {'ok': True}
    if cmd == 'set_volume':
        from extensions import setvolume
        setvolume(int(args.get('volume')))
        return {'ok': True}
    return None


def _ack(cid, status, error, session_id=None):
    """Tell remote what happened: over the socket, else the HTTP fallback."""
    payload = {'id': cid, 'status': status, 'error': error or ''}
    import integrations.relay_ws as rw
    try:
        rw.send_event('producer_ack', payload)
        return True
    except Exception:
        pass
    try:
        import requests
        from sql import appsettingGet
        url = (appsettingGet('relay_url', '') or '').rstrip('/')
        sid = session_id or appsettingGet('relay_session_id', '')
        secret = appsettingGet('relay_secret', '')
        if not url or not sid:
            return False
        requests.post(f'{url}/api/v1/session/{sid}/producer/ack', json=payload,
                      headers={'X-Relay-Secret': secret, 'Content-Type': 'application/json'},
                      timeout=5)
        return True
    except Exception as exc:
        log.info('producer ack fallback failed: %s', exc)
        return False

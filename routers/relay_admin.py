"""Remote relay admin (ported from routes/relay_admin.py). The /ttrpg/relay
JSON paths stay verbatim (the TTRPG layout's health banner, the status page's
presence poll and the relay portal's server-to-server calls hit them); the
three render_template pages became /api/v1/relay/{page,party,rolls}."""
import contextvars
import logging
import os
import time

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import core.config as config
import core.events as events
from routers._util import form_or_json, json_body
from security.deps import require_dm
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)

router = APIRouter(prefix='/ttrpg/relay')
api = APIRouter(prefix='/api/v1/relay')
open_router = api


# ── helpers ───────────────────────────────────────────────────────────────────

def _relay_cfg():
    return {
        'enabled':          appsettingGet('relay_enabled',         '0'),
        'url':              appsettingGet('relay_url',             ''),
        'secret':           appsettingGet('relay_secret',          ''),
        'session_id':       appsettingGet('relay_session_id',      ''),
        'code':             appsettingGet('relay_session_code',    ''),
        'last_sync':        appsettingGet('relay_last_sync',       '—'),
        'roll_cleared_at':  appsettingGet('relay_roll_cleared_at', ''),
        'audio_enabled':    appsettingGet('relay_audio_enabled',   '1'),
        'audio_bitrate':    appsettingGet('relay_audio_bitrate',   '128'),
        'audio_profile':    appsettingGet('relay_audio_profile',   'low'),
        'audio_gain':       appsettingGet('relay_audio_gain',      '50'),
        # set by boot.start_integrations when a start crashed during relay
        # bring-up and the relay was auto-disabled (see relay_guard.py)
        'boot_tripped':     appsettingGet('relay_boot_tripped',    ''),
    }


def _public_cfg(cfg):
    """The page context minus the shared secret (never rendered; the old
    template left the secret input blank too)."""
    out = {k: v for k, v in cfg.items() if k != 'secret'}
    out['secret_set'] = bool(cfg['secret'])
    return out


# The old routes flash()ed as they went; the SPA gets the same sentences
# back in {'ok', 'message'}. Collected per request through a context var so
# helpers shared by several endpoints (_start_session) keep flashing.
_messages = contextvars.ContextVar('relay_admin_messages', default=None)


def _flash(message, category='warning'):
    lst = _messages.get()
    if lst is not None:
        lst.append(message)


class _collect:
    def __enter__(self):
        self.lst = []
        self._tok = _messages.set(self.lst)
        return self.lst

    def __exit__(self, *exc):
        _messages.reset(self._tok)
        return False


def _sync_age(cfg):
    """Seconds since the receiver's last successful poll (UTC
    '%Y-%m-%d %H:%M:%S' in relay_last_sync), None when never."""
    from datetime import datetime, timezone
    try:
        ts = datetime.strptime(cfg['last_sync'], '%Y-%m-%d %H:%M:%S')
        return int((datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds())
    except (ValueError, TypeError):
        return None


def _fetch_presence(cfg):
    presence = {}
    try:
        presp = requests.get(
            cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/presence",
            headers={'X-Relay-Secret': cfg['secret']},
            timeout=5,
        )
        if presp.ok:
            presence = presp.json().get('presence', {}) or {}
    except Exception as e:
        log.debug('presence fetch error: %s', e)
    return presence


# ── page data ─────────────────────────────────────────────────────────────────

@api.get('/page')
def status(user=Depends(require_dm)):
    import json as _json
    cfg = _relay_cfg()
    logged_in = []

    # Age of the last successful receiver poll, so a stalled sync is visible
    # at the table instead of being discovered mid-combat.
    sync_age = _sync_age(cfg)

    if cfg['session_id'] and cfg['url'] and cfg['enabled'] == '1':
        try:
            resp = requests.get(
                cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/sync",
                headers={'X-Relay-Secret': cfg['secret']},
                timeout=5,
            )
            if resp.ok:
                for rc in resp.json().get('characters', []):
                    if not rc.get('has_joined'):
                        continue
                    sheet = {}
                    try:
                        sheet = _json.loads(rc.get('sheet_json') or '{}')
                    except Exception:
                        pass
                    hp_current = rc.get('hp_current') or 0
                    hp_max     = rc.get('hp_max') or 1
                    logged_in.append({
                        'player_name':  rc.get('player_name', ''),
                        'username':     rc.get('username', ''),
                        'display_name': rc.get('display_name', ''),
                        'char_class':   sheet.get('class', '—'),
                        'level':        sheet.get('level', '—'),
                        'hp_current':   hp_current,
                        'hp_max':       hp_max,
                        'hp_pct':       round(100 * hp_current / max(1, hp_max)),
                        'joined_at':    (rc.get('joined_at') or '')[:16].replace('T', ' '),
                    })
        except Exception as e:
            log.debug('status logged-in fetch error: %s', e)

        # Live presence: the relay marks players present on SSE connect +
        # 30s heartbeats and absent on disconnect, so this distinguishes
        # "has an account and joined at some point" from "connected right
        # now". Missing from the dict or stale-hearted (>90s) = offline.
        presence = _fetch_presence(cfg)
        for p in logged_in:
            # Presence keys vary by relay version: character name on newer
            # code, username on an older one, the login's display name on the
            # current portal (its token names the player that way) — accept any.
            age = presence.get(p['player_name'])
            if age is None:
                age = presence.get(p['username'])
            if age is None:
                age = presence.get(p['display_name'])
            p['online'] = age is not None and age < 90

        # Spectator logins — an account the GM synced but NO character assigned
        # yet — have no row in the sync payload's characters list, so they'd be
        # invisible here. Presence still tracks them by display name (the relay
        # falls back to the login's name when there's no character), so surface
        # any presence entry that didn't match a character row.
        known = set()
        for p in logged_in:
            known.update((p['player_name'], p['username'], p['display_name']))
        for name, age in presence.items():
            if name in known:
                continue
            logged_in.append({
                'player_name':  name,
                'username':     '',
                'display_name': name,
                'char_class':   '—',
                'level':        '—',
                'hp_current':   0,
                'hp_max':       0,
                'hp_pct':       0,
                'joined_at':    '',
                'online':       age is not None and age < 90,
                'no_character': True,
            })

    return {'cfg': _public_cfg(cfg), 'logged_in': logged_in, 'sync_age': sync_age}


@api.get('/party')
def party(user=Depends(require_dm)):
    import json as _json
    cfg = _relay_cfg()
    relay_chars = []
    error = None

    if cfg['session_id'] and cfg['url']:
        try:
            resp = requests.get(
                cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/sync",
                headers={'X-Relay-Secret': cfg['secret']},
                timeout=8,
            )
            resp.raise_for_status()
            raw_chars = resp.json().get('characters', [])
            for rc in raw_chars:
                # Only show players who have actually logged in on the relay site
                if not rc.get('has_joined', False):
                    continue
                sheet = {}
                try:
                    sheet = _json.loads(rc.get('sheet_json') or '{}')
                except Exception:
                    pass
                hp_current = rc.get('hp_current', 0) or 0
                hp_max     = rc.get('hp_max', 1) or 1
                relay_chars.append({
                    'player_name': rc.get('player_name', ''),
                    'sheet':       sheet,
                    'hp_current':  hp_current,
                    'hp_max':      hp_max,
                    'hp_pct':      round(100 * hp_current / max(1, hp_max)),
                    'updated_at':  (rc.get('updated_at') or '')[:16].replace('T', ' '),
                    'joined_at':   (rc.get('joined_at') or '')[:16].replace('T', ' '),
                    'char_id':     rc.get('id', ''),
                })
        except Exception as e:
            log.warning('party relay fetch error: %s', e)
            error = str(e)

    return {'party': relay_chars, 'cfg': _public_cfg(cfg), 'error': error}


@api.get('/rolls')
def rolls(user=Depends(require_dm)):
    from models.tblRollLog import tblRollLog

    session_id = appsettingGet('relay_session_id', '')
    entries = []

    if session_id:
        try:
            sid = int(session_id)
        except (ValueError, TypeError):
            sid = None

        if sid:
            entries = (tblRollLog.query
                       .filter_by(session_id=sid)
                       .order_by(tblRollLog.id.desc())
                       .limit(200)
                       .all())

    return {'entries': [{'id': e.id, 'rolled_at': e.rolled_at, 'player_name': e.player_name,
                         'roll_expr': e.roll_expr, 'result': e.result,
                         'breakdown': e.breakdown} for e in entries],
            'session_id': session_id}


# ── verbatim JSON paths ───────────────────────────────────────────────────────

def _health():
    """Lightweight relay-health check for the DM banner on every TTRPG page.

    Signals: relay_last_sync (receiver heartbeat — written after each
    successful poll, so staleness means the portal<->local sync is broken)
    and relay_push_last_drop (a push the queue gave up on — silent data loss
    toward the portal). Only alarms when the relay is enabled AND a session
    exists; an idle relay is not an error."""
    from datetime import datetime, timezone
    cfg = _relay_cfg()
    if cfg['enabled'] != '1' or not cfg['url'] or not cfg['session_id']:
        return {'enabled': False, 'ok': True, 'problems': []}

    problems = []

    # receiver heartbeat
    sync_age = _sync_age(cfg)
    if sync_age is None:
        problems.append('Relay sync has not completed yet — players are not syncing.')
    elif sync_age > 90:
        mins = sync_age // 60
        problems.append(f'Relay sync stalled — last contact '
                        f'{f"{mins}m" if mins else f"{sync_age}s"} ago. '
                        f'Player moves and sheet changes are NOT reaching this server.')

    # dropped pushes (local -> relay data loss)
    drop = appsettingGet('relay_push_last_drop', '') or ''
    if drop:
        try:
            ts_s, key, err = drop.split('|', 2)
            age = (datetime.now(timezone.utc).replace(tzinfo=None)
                   - datetime.strptime(ts_s, '%Y-%m-%d %H:%M:%S')).total_seconds()
            if age < 600:   # only recent drops — old noise self-clears
                if '/session/' in err and cfg['session_id'] not in err:
                    # drop targeted a session that is no longer ours — stale
                    pass
                elif '404' in err:
                    # the relay doesn't know our session (redeployed, or a New
                    # Session was made from another ScenePlay box) — re-pushing
                    # can't help; a fresh session can.
                    problems.append('The relay no longer knows this session '
                                    '(it may have restarted, or New Session was used '
                                    'on another server). Create a New Session and have '
                                    'players log in again.')
                else:
                    problems.append(f'A push to the relay was dropped {int(age // 60)}m ago '
                                    f'({key}: {err}). Remote players may be out of date — '
                                    f'use Sync Characters to re-push.')
        except ValueError:
            pass

    # transport: 'connected' = GM WebSocket live (poll paused); anything else
    # means the legacy 2s poll is carrying sync. Shown on the status page and
    # used by the integration drill.
    try:
        import integrations.relay_ws as relay_ws
        transport = 'ws' if relay_ws.connected() else f'polling ({relay_ws.state()})'
    except Exception:
        transport = 'polling'
    return {'enabled': True, 'ok': not problems, 'problems': problems,
            'sync_age': sync_age, 'transport': transport}


@router.get('/api/health')
def api_health(user=Depends(require_dm)):
    return _health()


def _presence():
    """Live online/offline per portal player, polled by the status page so
    the Players Online table updates without a refresh."""
    cfg = _relay_cfg()
    if cfg['enabled'] != '1' or not cfg['url'] or not cfg['session_id']:
        return {'enabled': False, 'online': {}}
    presence = _fetch_presence(cfg)
    # Same liveness rule as the page render: heartbeat younger than 90s
    online = {name: (age is not None and age < 90)
              for name, age in presence.items()}
    return {'enabled': True, 'online': online}


@router.get('/api/presence')
def api_presence(user=Depends(require_dm)):
    return _presence()


def relay_snapshot():
    """The SSE `relay` topic: health (what the layout banner reads) plus the
    presence map the status page reads, plus the bits of config the banner
    and pills show. Presence comes from the GM WebSocket cache when it is
    connected (relay_broadcaster.get_presence), the legacy HTTP GET otherwise."""
    snap = _health()
    snap['online'] = {}
    if snap['enabled']:
        try:
            import integrations.relay_broadcaster as relay_broadcaster
            presence = relay_broadcaster.get_presence() or {}
            snap['online'] = {name: (age is not None and age < 90)
                              for name, age in presence.items()}
        except Exception as e:
            log.debug('relay_snapshot presence error: %s', e)
    snap['code'] = appsettingGet('relay_session_code', '')
    snap['last_sync'] = appsettingGet('relay_last_sync', '—')
    # Stamped so a page that just rendered fresher data (its own presence
    # fetch) can ignore an older snapshot replayed in the SSE hello.
    snap['ts'] = time.time()
    return snap


def _emit_relay():
    """After a mutation: push the fresh snapshot to SSE subscribers now
    rather than waiting for the derived producer's next tick."""
    try:
        events.emit('relay', relay_snapshot())
    except Exception:
        pass


# ── mutations (old form+redirect endpoints; the SPA toasts `message`) ────────

_NO_INTEGRATIONS = ('Relay is switched off on this instance (SP_INTEGRATIONS=0) — '
                    'nothing was sent to the relay.')


def _integrations_off():
    """SP_INTEGRATIONS=0 (tests, dev instances on a DB copy) must never reach
    the relay portal: the copy carries the live box's relay URL and secret,
    and a session create there would evict the real table's players."""
    return not config.INTEGRATIONS


@router.post('/toggle')
def toggle(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    from core.appctx import ctx
    current = appsettingGet('relay_enabled', '0')
    new_val = '0' if current == '1' else '1'
    if new_val == '1' and _integrations_off():
        return {'ok': False, 'message': _NO_INTEGRATIONS, 'enabled': False,
                'code': appsettingGet('relay_session_code', '')}
    appsettingSet('relay_enabled', new_val)

    with _collect() as msgs:
        if new_val == '1':
            # Same crash guard as the boot auto-start: if this enable takes the
            # box down (low-memory OOM), the next start skips the relay instead
            # of boot-looping. Clearing relay_boot_tripped dismisses the warning.
            import integrations.relay_guard as relay_guard
            appsettingSet('relay_boot_tripped', '')
            relay_guard.arm()
            # Which relay session to engage — the status page asks the DM
            # (dropdown) before submitting:
            #   'reuse'  recreate the session under the code players already
            #            have (same as ↺ Reuse Code)
            #   'new'    mint a fresh code (same as ↻ New Session)
            #   ''       legacy/plain enable: leave the relay session alone
            mode = (form.get('session_mode') or '').strip()
            code = None
            if mode in ('reuse', 'new'):
                cfg = _relay_cfg()
                if mode == 'reuse' and cfg['session_id'] and cfg['code']:
                    code, _sid = _start_session(requested_id=cfg['session_id'],
                                                requested_code=cfg['code'])
                else:
                    code, _sid = _start_session()
            _start_receiver()
            import integrations.relay_ws as relay_ws
            relay_ws.start(ctx)
            if code is None:
                # _start_session already pushed the party into the fresh session.
                import integrations.relay_broadcaster as relay_broadcaster
                relay_broadcaster.push_all_characters()
                relay_broadcaster.push_session_users()
                relay_broadcaster.push_character_feeds()
                relay_broadcaster.push_library()   # same set as generate-code / Party Sync
            relay_guard.disarm_after_grace()
            if code:
                _flash(f'Relay enabled — join code {code}'
                       + (' (unchanged, players keep it)' if mode == 'reuse' else ' (new — send it to the players)')
                       + '. Party pushed.')
            else:
                _flash('Relay enabled — receiver started and party synced.')
        else:
            import integrations.relay_ws as relay_ws
            relay_ws.stop()
            _stop_receiver()
            _flash('Relay disabled.')

    _emit_relay()
    return {'ok': True, 'message': ' '.join(msgs), 'enabled': new_val == '1',
            'code': appsettingGet('relay_session_code', '')}


@router.post('/save-config')
def save_config(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    relay_url    = (form.get('relay_url') or '').strip()
    relay_secret = (form.get('relay_secret') or '').strip()
    url_changed = secret_changed = False
    if relay_url:
        url_changed = relay_url != appsettingGet('relay_url', '')
        appsettingSet('relay_url',    relay_url)
    if relay_secret:
        secret_changed = relay_secret != appsettingGet('relay_secret', '')
        appsettingSet('relay_secret', relay_secret)
    if url_changed or secret_changed:
        # a different relay/credentials: reconnect the GM WebSocket (also
        # clears a previous 'unsupported' verdict — the new relay may have it)
        import integrations.relay_ws as relay_ws
        relay_ws.restart()
    # Checkbox: absent from the form data when unchecked. Applies at the
    # next track start / push rotation (relay_audio_stream re-reads config).
    appsettingSet('relay_audio_enabled',
                  '1' if form.get('relay_audio_enabled') else '0')
    bitrate = form.get('relay_audio_bitrate') or '128'
    appsettingSet('relay_audio_bitrate',
                  bitrate if bitrate in ('64', '96', '128') else '128')
    profile = form.get('relay_audio_profile') or 'low'
    appsettingSet('relay_audio_profile',
                  profile if profile in ('low', 'smooth') else 'low')
    gain = form.get('relay_audio_gain') or '50'
    appsettingSet('relay_audio_gain',
                  gain if gain in ('25', '50', '75', '100', '150') else '50')
    _emit_relay()
    # The page auto-saves over fetch (same treatment as the OBS Broadcast form).
    return {'ok': True, 'reconnecting': url_changed or secret_changed,
            'message': 'Relay configuration saved.'}


def _start_session(requested_id=None, requested_code=None):
    """Create/reset the relay session and push everything — the ONE path both
    buttons share. With a requested id+code the relay recreates the session
    under that identity (Reuse Code: players keep the code they have); without,
    it mints fresh ones (New Session). Returns the new (code, session_id) or
    (None, None) after flashing an error."""
    cfg = _relay_cfg()
    if not cfg['url'] or not cfg['secret']:
        _flash('Set relay URL and secret first.')
        return None, None

    # ALWAYS request an identity WE chose (the relay honors requested id+code —
    # its mid-campaign recovery feature). This makes create verifiable: if the
    # response is lost (Render cold start, purge slower than the timeout) we
    # can probe whether the session exists and treat it as the success it was
    # — instead of flashing a false error, and (worse, for New Session) the
    # relay holding a fresh session whose id nobody knows.
    if not (requested_id and requested_code):
        import uuid as _uuid
        import secrets as _secrets
        import string as _string
        requested_id   = str(_uuid.uuid4())
        requested_code = ''.join(_secrets.choice(_string.ascii_uppercase + _string.digits)
                                 for _ in range(6))
    payload = {'session_id': requested_id, 'code': requested_code}

    data = None
    try:
        resp = requests.post(
            cfg['url'].rstrip('/') + '/api/v1/session/create',
            headers={'X-Relay-Secret': cfg['secret'], 'Content-Type': 'application/json'},
            json=payload,
            # Generous: a spun-down Render instance takes ~30s to wake, and the
            # old 8s window reported failure for creates that then completed.
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # Did the create actually land despite the lost/failed response?
        try:
            chk = requests.get(
                cfg['url'].rstrip('/') + f'/api/v1/session/{requested_id}/sync',
                headers={'X-Relay-Secret': cfg['secret']}, timeout=8)
            if chk.ok:
                data = {'session_id': requested_id, 'code': requested_code}
                log.warning('session create response lost (%s) — but the relay '
                            'has the session; continuing as success', e)
        except Exception:
            pass
        if data is None:
            log.warning('session start relay error: %s', e)
            _flash(f'Could not reach relay: {e}')
            return None, None

    step = 'validate relay response'
    try:
        code       = data.get('code', '')
        session_id = data.get('session_id', '')
        if not code or not session_id:
            _flash('Relay returned an unexpected response — check relay logs.')
            return None, None

        step = 'store session settings'
        appsettingSet('relay_session_code', code)
        appsettingSet('relay_session_id',   session_id)

        # Reset relay session = all relay token rows purged and seq counters
        # restarted; drop the local relay-seq mirror so no stale value can
        # collide with (and swallow) a fresh move.
        #
        # Same restart hazard for ROLL ids and MUTATION ids: the relay purges
        # its roll_log/mutations with the session, and on a redeployed relay
        # (fresh DB) the AUTOINCREMENT counters start over at 1 — so relay ids
        # recorded locally are from a dead lifetime and collide with the new
        # session's ids, making the receiver's dedup swallow every fresh roll
        # and HP/sheet mutation. Strip the markers: tblRollLog keeps its rows
        # (full history) minus the ids; the 50-roll display feed drops its
        # relay-origin rows outright (NULLing them would let the echo-claim
        # dedup swallow new rolls that match a stale row's signature).
        step = 'reset local relay mirrors'
        from core.db import db
        from models.tblTokenPositions import tblTokenPositions
        from models.tblRollLog import tblRollLog
        from models.ttrpg import tblDiceRolls
        import time as _time
        for attempt in (1, 2):
            try:
                # End the read transaction this request has held open since
                # the login lookup — ACROSS the long relay HTTP call above.
                # Its WAL snapshot is stale by now (the receiver thread
                # commits every 2s) and writing on it fails instantly with
                # SQLITE_BUSY_SNAPSHOT ("database is locked" — busy timeout
                # does not apply). A fresh transaction writes cleanly.
                db.session.rollback()
                tblTokenPositions.query.delete(synchronize_session=False)
                tblRollLog.query.filter(tblRollLog.relay_roll_id.isnot(None)) \
                    .update({'relay_roll_id': None}, synchronize_session=False)
                tblDiceRolls.query.filter(tblDiceRolls.relay_roll_id.isnot(None)) \
                    .delete(synchronize_session=False)
                db.session.commit()
                break
            except Exception as e:
                db.session.rollback()
                if attempt == 2 or 'locked' not in str(e).lower():
                    raise
                _time.sleep(1.5)   # one retry: outlast a transient writer
        step = 'clear applied-mutation ledger'
        appsettingSet('relay_applied_mutation_ids', '[]')

        # Push drops recorded against the PREVIOUS session are moot now —
        # clear them so the health banner doesn't nag about a dead session.
        step = 'clear push-drop flag'
        appsettingSet('relay_push_last_drop', '')

        # Push all current party characters and D&D library into the fresh session immediately
        import integrations.relay_broadcaster as relay_broadcaster
        step = 'queue character push'
        relay_broadcaster.push_all_characters()
        step = 'queue user push'
        relay_broadcaster.push_session_users()
        step = 'queue feed push'
        relay_broadcaster.push_character_feeds()
        step = 'queue library push'
        relay_broadcaster.push_library()
        # The GM WebSocket is bound to a session id — reconnect under the new one
        step = 'restart gm websocket'
        import integrations.relay_ws as relay_ws
        relay_ws.restart()
        return code, session_id
    except Exception as e:
        # The session EXISTS on the relay at this point — don't report it as
        # unreachable. Local bookkeeping/push failed; characters can be re-sent.
        log.exception('session start post-create error at step %r', step)
        try:
            import traceback
            from datetime import datetime as _dt
            os.makedirs(config.INSTANCE_DIR, exist_ok=True)
            with open(os.path.join(config.INSTANCE_DIR, 'relay_last_error.log'),
                      'w', encoding='utf-8') as f:
                f.write(f'{_dt.now():%Y-%m-%d %H:%M:%S} step={step}\n')
                f.write(traceback.format_exc())
        except Exception:
            pass
        _flash(f'Session created (join code {code}), but step "{step}" failed: '
               f'{e}. Use Sync Characters to re-push the party.')
        return code, session_id


@router.post('/generate-code')
def generate_code(user=Depends(require_dm)):
    if _integrations_off():
        return {'ok': False, 'message': _NO_INTEGRATIONS, 'code': None}
    with _collect() as msgs:
        code, _sid = _start_session()
        if code:
            _flash(f'New session created — join code: {code}. Party pushed to relay.')
    _emit_relay()
    return {'ok': bool(code), 'message': ' '.join(msgs), 'code': code}


@router.post('/reuse-code')
def reuse_code(user=Depends(require_dm)):
    """Exactly New Session, except the relay recreates the session under the
    join code (and session_id) we already have — so mid-campaign the GM can
    reset the relay without re-sending a code to every player. Preserving the
    session_id also keeps still-open portals logged in (their tokens name it)."""
    if _integrations_off():
        return {'ok': False, 'message': _NO_INTEGRATIONS, 'code': None}
    cfg = _relay_cfg()
    if not cfg['session_id'] or not cfg['code']:
        return {'ok': False, 'message': 'No previous session to reuse — generate a code first.',
                'code': None}

    with _collect() as msgs:
        code, _sid = _start_session(requested_id=cfg['session_id'],
                                    requested_code=cfg['code'])
        if code == cfg['code']:
            _flash(f'Session reset — join code {code} unchanged, party pushed. '
                   'Players keep the code they already have.')
        elif code:
            # An older relay ignores the requested identity and mints fresh ones.
            _flash(f'Relay issued a NEW code: {code} (relay is running an older '
                   'version). Party pushed — players will need the new code.')
    _emit_relay()
    return {'ok': bool(code), 'message': ' '.join(msgs), 'code': code}


@router.post('/sync-characters')
def sync_characters(user=Depends(require_dm)):
    if _integrations_off():
        return {'ok': False, 'message': _NO_INTEGRATIONS}
    import integrations.relay_broadcaster as relay_broadcaster
    relay_broadcaster.push_all_characters()
    relay_broadcaster.push_session_users()
    relay_broadcaster.push_character_feeds()
    relay_broadcaster.push_library()
    return {'ok': True, 'message': 'Party characters, user accounts and library pushed to relay.'}


@router.post('/clear-rolls')
def clear_rolls(user=Depends(require_dm)):
    # Same helper the battlemap's Clear Rolls button calls, so the two can't
    # drift apart on what "cleared" means (notably the relay watermark).
    from routers.ttrpg import clear_roll_history
    removed = clear_roll_history()
    events.emit('dice', {'kind': 'clear'})
    return {'ok': True, 'removed': removed,
            'message': 'Local roll history cleared. The receiver will ignore relay rolls '
                       'made before this point.'}


# ── Server-to-server API (called by relay, no browser session required) ──────

def _require_relay_secret(request: Request):
    """Return None if the request carries the correct relay secret, else an error response."""
    stored = appsettingGet('relay_secret', '')
    incoming = request.headers.get('X-Relay-Secret', '')
    if not stored or incoming != stored:
        return JSONResponse({'ok': False, 'error': 'unauthorized'}, status_code=401)
    return None


@router.post('/api/auth/verify')
def api_auth_verify(request: Request, data: dict = Depends(json_body)):
    """Relay calls this to verify a player's ScenePlay credentials.

    Request  (JSON):  { "username": str, "password": str }
    Auth:             X-Relay-Secret header

    Response 200:     { ok, user_id, username, display_name,
                        relay_session_id, character: { name, class, level,
                        hp_current, hp_max, ac, speed } | null }
    Response 401:     { ok: false, error }
    """
    err = _require_relay_secret(request)
    if err:
        return err

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return JSONResponse({'ok': False, 'error': 'missing credentials'}, status_code=400)

    from models.user import tblUsers
    from models.ttrpg import tblSessions
    import core.urls as urls

    user = tblUsers.query.filter_by(username=username, active=1).first()
    if not user or not user.check_password(password):
        return JSONResponse({'ok': False, 'error': 'invalid credentials'}, status_code=401)

    # Find the character this user has in the active session
    active_sess = tblSessions.query.filter_by(status='active').first()
    character   = None
    if active_sess:
        for sp in active_sess.party:
            char = sp.character
            if char and char.user_id == user.user_id:
                portrait_url = ''
                if char.portrait_path:
                    portrait_url = urls.static_url(f'uploads/portraits/{char.portrait_path}',
                                                   external=True)
                character = {
                    'name':         char.name,
                    'class':        char.char_class,
                    'race':         char.race,
                    'level':        char.level,
                    'hp_current':   char.hp_current,
                    'hp_max':       char.hp_max,
                    'ac':           char.ac,
                    'speed':        char.speed,
                    'portrait_url': portrait_url,
                }
                break

    return {
        'ok':               True,
        'user_id':          user.user_id,
        'username':         user.username,
        'display_name':     user.display_name,
        'relay_session_id': appsettingGet('relay_session_id', ''),
        'character':        character,
    }


@router.get('/api/session/info')
def api_session_info(request: Request):
    """Relay calls this to get current session and map state.

    Auth: X-Relay-Secret header

    Response 200: { relay_session_id, code, sceneplay_session_id,
                    map: { url, grid_cols, grid_rows, tokens } | null }
    """
    err = _require_relay_secret(request)
    if err:
        return err

    from models.ttrpg import tblSessions, tblBattleMaps
    from core.db import db
    import traceback as _tb
    import core.urls as urls

    cfg = _relay_cfg()

    try:
        active_sess = tblSessions.query.filter_by(status='active').first()
        map_data    = None

        if active_sess:
            bm = tblBattleMaps.query.filter_by(
                session_id=active_sess.session_id, is_active=1).first()
            if bm:
                bg_url = (urls.static_url(f'uploads/battlemaps/{bm.bg_image}', external=True)
                          if bm.bg_image else '')
                tokens = []
                for t in bm.tokens:
                    tok = {
                        'token_id':    t.token_id,
                        'token_type':  t.entity_type,
                        'label':       '',
                        'x_pct':       t.col / max(1, bm.grid_cols - 1),
                        'y_pct':       t.row / max(1, bm.grid_rows - 1),
                        'character_id': None,
                    }
                    if t.entity_type == 'player':
                        from models.ttrpg import tblCharacters
                        char = db.session.get(tblCharacters, t.entity_id)
                        if char:
                            tok['label']        = char.name
                            tok['character_id'] = t.entity_id
                            tok['hp_current']   = char.hp_current
                            tok['hp_max']       = char.hp_max
                    elif t.entity_type == 'monster':
                        from models.ttrpg import tblSessionMonsters
                        sm = db.session.get(tblSessionMonsters, t.entity_id)
                        if sm:
                            tok['label']      = sm.display_name
                            tok['hp_current'] = sm.hp_current
                            tok['hp_max']     = sm.hp_max
                    tokens.append(tok)
                map_data = {
                    'url':       bg_url,
                    'grid_cols': bm.grid_cols,
                    'grid_rows': bm.grid_rows,
                    'tokens':    tokens,
                }
    except Exception as exc:
        log.error('api_session_info error: %s\n%s', exc, _tb.format_exc())
        return JSONResponse({'error': str(exc), 'trace': _tb.format_exc()}, status_code=500)

    return {
        'relay_session_id':    cfg['session_id'],
        'code':                cfg['code'],
        'sceneplay_session_id': active_sess.session_id if active_sess else None,
        'map':                 map_data,
    }


# ── receiver thread helpers ───────────────────────────────────────────────────

def _start_receiver():
    try:
        from core.appctx import ctx
        import integrations.relay_receiver as relay_receiver
        relay_receiver.start(ctx)
    except Exception as e:
        log.warning('Could not start relay receiver: %s', e)


def _stop_receiver():
    try:
        import integrations.relay_receiver as relay_receiver
        relay_receiver.stop()
    except Exception as e:
        log.warning('Could not stop relay receiver: %s', e)


# derived SSE topic: health + presence for the layout banner and the status
# page. 10 s = the old status-page presence poll; the fetch is a cached WS
# snapshot when the GM socket is up and a 5 s-timeout HTTP GET otherwise (it
# runs in the hub's worker thread, never on the event loop).
events.register_derived('relay', relay_snapshot, 10.0)

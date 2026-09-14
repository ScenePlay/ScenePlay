"""JWT login, first-run setup, refresh, password change, local-file password
recovery (ported from routes/auth.py) and the SPA bootstrap payload."""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

import core.config as config
from core.db import db
from models.user import tblUsers
from schemas.auth import (ChangePasswordRequest, LoginRequest, RecoverGenerateRequest,
                          RecoverResetRequest, SetupRequest)
from security.deps import ApiError, get_current_user, require_user, sceneplay_locked_for
from security.jwt import issue_token

log = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/auth')


# ── Local-access password recovery ─────────────────────────────────────────────
# Self-service reset with the server's FILESYSTEM as the root of trust: the
# one-time code is written to a text file on the box, so retrieving it proves
# local access. Codes are single-use, expire, and rate-limit.

RECOVERY_DIR = os.path.join(config.ROOT, 'password_recovery')
_RECOVERY_FILE      = 'recovery_code.txt'
_RECOVERY_TTL_MIN   = 15
_RECOVERY_MAX_TRIES = 5
_RECOVERY_ALPHABET  = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _recovery_norm(code):
    return (code or '').replace('-', '').replace(' ', '').strip().upper()


def _recovery_begin(username):
    from sql import appsettingSet
    code = '-'.join(''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4))
                    for _ in range(2))
    expires = (datetime.utcnow() + timedelta(minutes=_RECOVERY_TTL_MIN)
               ).strftime('%Y-%m-%d %H:%M:%S')
    os.makedirs(RECOVERY_DIR, exist_ok=True)
    path = os.path.join(RECOVERY_DIR, _RECOVERY_FILE)
    with open(path, 'w') as f:
        f.write(
            'ScenePlay password recovery\n'
            '===========================\n\n'
            f'Account:  {username}\n'
            f'Code:     {code}\n\n'
            f'Enter this code on the password recovery page within '
            f'{_RECOVERY_TTL_MIN} minutes.\n'
            'This file is deleted automatically once the code is used or expires.\n'
        )
    appsettingSet('pw_recovery_user',     username)
    appsettingSet('pw_recovery_hash',     hashlib.sha256(_recovery_norm(code).encode()).hexdigest())
    appsettingSet('pw_recovery_expires',  expires)
    appsettingSet('pw_recovery_attempts', '0')
    log.warning('Password recovery code generated for %r -> %s', username, path)
    return path


def _recovery_clear():
    from sql import appsettingSet
    appsettingSet('pw_recovery_hash', '')
    appsettingSet('pw_recovery_user', '')
    try:
        os.remove(os.path.join(RECOVERY_DIR, _RECOVERY_FILE))
    except OSError:
        pass


def _recovery_check(username, code):
    from sql import appsettingGet, appsettingSet
    stored = appsettingGet('pw_recovery_hash', '') or ''
    if not stored:
        return False, 'No recovery code is active — generate one first.'
    expires = appsettingGet('pw_recovery_expires', '') or ''
    if not expires or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') > expires:
        _recovery_clear()
        return False, 'The recovery code has expired — generate a new one.'
    try:
        tries = int(appsettingGet('pw_recovery_attempts', '0') or 0) + 1
    except ValueError:
        tries = 1
    if tries > _RECOVERY_MAX_TRIES:
        _recovery_clear()
        return False, 'Too many attempts — generate a new code.'
    appsettingSet('pw_recovery_attempts', str(tries))
    if username != (appsettingGet('pw_recovery_user', '') or ''):
        return False, 'The active code was generated for a different username.'
    digest = hashlib.sha256(_recovery_norm(code).encode()).hexdigest()
    if not hmac.compare_digest(digest, stored):
        left = _RECOVERY_MAX_TRIES - tries
        return False, f'Incorrect code ({left} attempt{"s" if left != 1 else ""} left).'
    return True, None


# ── helpers ───────────────────────────────────────────────────────────────────

def _token_for(user, ttl_hours=None):
    ttl = timedelta(hours=ttl_hours) if ttl_hours else None
    return issue_token(user, ttl)


def _health():
    """Navbar badges — the old Jinja context processors, as one payload."""
    from datetime import timezone
    out = {'relay': {'on': False, 'stale': False, 'failing': False, 'msg': ''},
           'obs': {'on': False, 'connected': False},
           'led_remote': {'failing': False, 'msg': ''},
           'wled': {'failing': False, 'msg': ''}}
    try:
        from sql import appsettingGet

        def _age(ts_s):
            ts = datetime.strptime(ts_s, '%Y-%m-%d %H:%M:%S')
            return (datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds()

        if appsettingGet('relay_enabled', '0') == '1':
            r = out['relay']
            r['on'] = True
            stale = True
            last = appsettingGet('relay_last_sync', '')
            if last and last != '—':
                try:
                    stale = _age(last) > 90
                except ValueError:
                    pass
            r['stale'] = stale
            drop = appsettingGet('relay_push_last_drop', '')
            if drop and '|' in drop:
                d_ts, _key, err = (drop.split('|', 2) + ['', ''])[:3]
                try:
                    if _age(d_ts) < 120:
                        r['failing'] = True
                        r['msg'] = err
                except ValueError:
                    pass
        if appsettingGet('obs_enabled', '0') == '1':
            out['obs']['on'] = True
            try:
                import integrations.obs_ws as obs_ws
                out['obs']['connected'] = obs_ws.connected()
            except Exception:
                pass

        def _recent(setting):
            rec = appsettingGet(setting, '')
            if rec and '|' in rec:
                ts_s, ip_addr, err = (rec.split('|', 2) + ['', ''])[:3]
                try:
                    if _age(ts_s) < 120:
                        return f'{ip_addr}: {err}'
                except ValueError:
                    pass
            return ''
        msg = _recent('remote_send_last_fail')
        if msg:
            out['led_remote'] = {'failing': True, 'msg': msg}
        msg = _recent('wled_send_last_fail')
        if msg:
            out['wled'] = {'failing': True, 'msg': msg}
    except Exception:
        pass
    return out


def bootstrap_payload(user):
    from version import __version__
    from sql import appsettingGetKeepMusicPlaying
    no_users = tblUsers.query.first() is None
    try:
        keep = bool(appsettingGetKeepMusicPlaying())
    except Exception:
        keep = False
    return {
        'user': user.to_dict() if user else None,
        'setup_needed': no_users,
        'no_users': no_users,
        'sceneplay_locked': sceneplay_locked_for(user),
        'version': __version__,
        'keep_music': keep,
        'workers': bool(config.WORKERS),
        'player_engine': config.PLAYER,
        'health': _health(),
    }


# ── routes ────────────────────────────────────────────────────────────────────

@router.get('/bootstrap')
def bootstrap(user=Depends(get_current_user)):
    return bootstrap_payload(user)


@router.post('/login')
def login(req: LoginRequest):
    user = tblUsers.query.filter_by(username=req.username.strip(), active=1).first()
    if not user or not user.check_password(req.password):
        raise ApiError(401, 'Invalid username or password.', code='bad_credentials',
                       detail={'no_users': tblUsers.query.first() is None})
    return {'token': _token_for(user, req.ttl_hours), 'user': user.to_dict()}


@router.post('/setup')
def setup(req: SetupRequest):
    """First-run only: create the initial DM account. Locked once any user exists."""
    if tblUsers.query.first():
        raise ApiError(409, 'Setup already completed.', code='setup_done')
    dm = tblUsers(
        username=req.username.strip(),
        display_name=req.display_name.strip(),
        role='dm',
        active=1,
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    dm.set_password(req.password)
    db.session.add(dm)
    db.session.commit()
    return {'token': _token_for(dm), 'user': dm.to_dict()}


@router.post('/refresh')
def refresh(user=Depends(require_user)):
    return {'token': _token_for(user), 'user': user.to_dict()}


@router.post('/change-password')
def change_password(req: ChangePasswordRequest, user=Depends(require_user)):
    if not user.check_password(req.current_password):
        raise ApiError(400, 'Current password is incorrect.')
    new_pw = req.new_password.strip()
    if not new_pw:
        raise ApiError(400, 'New password cannot be empty.')
    if new_pw != req.confirm_password.strip():
        raise ApiError(400, 'New passwords do not match.')
    user.set_password(new_pw)
    db.session.commit()
    # the password version changed: hand back a token that still works
    return {'ok': True, 'message': 'Password updated successfully.', 'token': _token_for(user)}


@router.post('/recover/generate')
def recover_generate(req: RecoverGenerateRequest):
    username = req.username.strip()
    if not tblUsers.query.filter_by(username=username, active=1).first():
        raise ApiError(400, 'No active account with that username.')
    path = _recovery_begin(username)
    return {'ok': True, 'code_path': path, 'ttl': _RECOVERY_TTL_MIN}


@router.post('/recover/reset')
def recover_reset(req: RecoverResetRequest):
    username = req.username.strip()
    new_pw = req.new_password.strip()
    if not username or not new_pw:
        raise ApiError(400, 'Username and new password are required.')
    if new_pw != req.confirm_password.strip():
        raise ApiError(400, 'New passwords do not match.')
    ok, err = _recovery_check(username, req.code)
    if not ok:
        raise ApiError(400, err)
    user = tblUsers.query.filter_by(username=username, active=1).first()
    if not user:
        raise ApiError(400, 'Account not found.')
    user.set_password(new_pw)
    db.session.commit()
    _recovery_clear()
    log.warning('Password reset via recovery code for %r', username)
    try:
        import integrations.relay_broadcaster as relay_broadcaster
        relay_broadcaster.push_session_users()
    except Exception:
        pass
    return {'ok': True, 'message': 'Password updated — log in with your new password.'}

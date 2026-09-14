"""FastAPI dependencies: bearer/query token -> user, role guards, the runtime
"DM-only ScenePlay" gate, and HMAC-signed URLs for file downloads."""
import hashlib
import hmac
import time
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import core.config as config
from security.jwt import AuthError, password_version, verify_token

_bearer = HTTPBearer(auto_error=False)


class ApiError(Exception):
    """JSON error with a stable `code` the SPA can switch on; app.py renders
    it as {"error": message, "code": code, "detail": detail}."""
    def __init__(self, status_code, message, code=None, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.detail = detail


def token_from_request(request: Request,
                       creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[str]:
    """Authorization: Bearer first; `?token=` only on GET (EventSource, <img>,
    <video>, <a download> cannot set headers)."""
    if creds and creds.scheme.lower() == 'bearer' and creds.credentials:
        return creds.credentials
    if request.method == 'GET':
        return request.query_params.get('token') or None
    return None


def get_current_user(request: Request, token: Optional[str] = Depends(token_from_request)):
    """The user behind the token, or None. Never raises: pages that are open
    to anonymous callers still want to know who is asking."""
    cached = getattr(request.state, 'user', None)
    if cached is not None or getattr(request.state, 'user_resolved', False):
        return cached
    request.state.user_resolved = True
    request.state.user = None
    if not token:
        return None
    try:
        claims = verify_token(token)
    except AuthError:
        return None
    try:
        from models.user import tblUsers
        from core.db import db
        user = db.session.get(tblUsers, int(claims.get('sub', 0)))
    except Exception:
        return None
    if user is None or not user.active:
        return None
    if claims.get('pv') != password_version(user.password_hash):
        return None            # password changed/reset since the token was issued
    request.state.user = user
    return user


def require_user(user=Depends(get_current_user)):
    if user is None:
        raise ApiError(401, 'login required', code='login_required')
    return user


def require_dm(user=Depends(get_current_user)):
    if user is None:
        raise ApiError(401, 'login required', code='login_required')
    if not user.is_dm():
        raise ApiError(403, 'DM only', code='dm_required')
    return user


def dm_only_sceneplay_enabled():
    """True when the 'DM-only ScenePlay' switch (Utilities > Access Control)
    is on. Any read failure means open — the historical LAN-trust default."""
    from sql import appsettingGet
    try:
        return str(appsettingGet('DMOnlyScenePlay', '0') or '0') == '1'
    except Exception:
        return False


def sceneplay_dm_gate(user=Depends(get_current_user)):
    """Router-level dependency for the ScenePlay controls/tables. With the
    switch off (default) everything stays LAN-open. With it on, non-DM
    callers get a JSON 403 — the SPA shows the locked notice."""
    if not dm_only_sceneplay_enabled():
        return user
    if user is not None and user.is_dm():
        return user
    raise ApiError(403, 'This server restricts ScenePlay to DM logins.',
                   code='sceneplay_locked')


def sceneplay_locked_for(user):
    return dm_only_sceneplay_enabled() and not (user is not None and user.is_dm())


# ── signed URLs (downloads that <a href>/<iframe> cannot send a bearer for) ──

def _sig(path, exp):
    return hmac.new(config.SECRET_KEY.encode(), f'{path}|{exp}'.encode(),
                    hashlib.sha256).hexdigest()[:32]


def signed_url(path, ttl_s=600):
    exp = int(time.time()) + int(ttl_s)
    sep = '&' if '?' in path else '?'
    return f'{path}{sep}exp={exp}&sig={_sig(path.split("?")[0], exp)}'


def signature_ok(request: Request) -> bool:
    try:
        exp = int(request.query_params.get('exp', '0'))
        sig = request.query_params.get('sig', '')
    except ValueError:
        return False
    if exp < time.time():
        return False
    return hmac.compare_digest(sig, _sig(request.url.path, exp))


def require_dm_or_signed(request: Request, user=Depends(get_current_user)):
    """A DM bearer/query token OR a valid short-lived signature."""
    if user is not None and user.is_dm():
        return user
    if signature_ok(request):
        return None
    raise ApiError(403, 'DM only', code='dm_required')

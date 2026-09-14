"""JWT HS256 tokens (PyJWT). Claims: sub (user id), un, role, pv (password
version: first 12 hex of sha256(password_hash) — a password change or DM
reset invalidates every outstanding token without a denylist), iat, exp."""
import hashlib
from datetime import datetime, timedelta, timezone

import jwt as _jwt

import core.config as config

ALGORITHM = 'HS256'
DEFAULT_TTL = timedelta(days=30)


class AuthError(Exception):
    pass


def password_version(password_hash):
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()[:12]


def issue_token(user, ttl=None):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': str(user.user_id),
        'un': user.username,
        'role': user.role,
        'pv': password_version(user.password_hash),
        'iat': now,
        'exp': now + (ttl or DEFAULT_TTL),
    }
    return _jwt.encode(payload, config.JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token):
    try:
        return _jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM], leeway=30)
    except _jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc

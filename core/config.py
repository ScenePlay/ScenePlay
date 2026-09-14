"""Process-wide configuration, read once at import.

Every path and port that used to be hardcoded (or pulled from the Flask app
object) lives here so a dev instance can run beside the live box:
  SP_PORT              listen port (8086)
  SP_DB_PATH           sqlite file (<root>/ScenePlay.db)
  SP_INSTANCE_DIR      secrets dir (<root>/instance)
  SP_UPLOADS_DIR       <root>/static/uploads
  SP_BACKUP_DIR        <root>/backups
  SP_WORKERS=0         skip the six queue/player workers
  SP_INTEGRATIONS=0    relay / OBS / LED-remote / WLED dispatch all no-op
  SP_CRON_APPLY=0      the cron wizard never writes the crontab
  SP_MPV_SOCKET_PREFIX mpv IPC socket prefix (/tmp/mpvsocket-)
  SP_PLAYER=ipc|classic music engine: one persistent mpv per player driven over its
                       JSON IPC (ipc, the default — see player_ipc.py) or one mpv per
                       track driven by shell/pkill (classic, the 1.x pipeline)
  SP_DEV=1             uvicorn --reload; implies SP_WORKERS=0
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def _flag(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off', '')


PORT = int(os.environ.get('SP_PORT', '8086'))
HOST = os.environ.get('SP_HOST', '0.0.0.0')
DB_PATH = os.path.abspath(os.environ.get('SP_DB_PATH') or os.path.join(ROOT, 'ScenePlay.db'))
INSTANCE_DIR = os.path.abspath(os.environ.get('SP_INSTANCE_DIR') or os.path.join(ROOT, 'instance'))
STATIC_DIR = os.path.join(ROOT, 'static')
UPLOADS_DIR = os.path.abspath(os.environ.get('SP_UPLOADS_DIR') or os.path.join(STATIC_DIR, 'uploads'))
BACKUP_DIR = os.path.abspath(os.environ.get('SP_BACKUP_DIR') or os.path.join(ROOT, 'backups'))
WEB_DIR = os.path.join(ROOT, 'web')
MIGRATIONS_DIR = os.path.join(ROOT, 'migrations')

DEV = _flag('SP_DEV', '0')
WORKERS = _flag('SP_WORKERS', '1') and not DEV
INTEGRATIONS = _flag('SP_INTEGRATIONS', '1')
CRON_APPLY = _flag('SP_CRON_APPLY', '1')
MPV_SOCKET_PREFIX = os.environ.get('SP_MPV_SOCKET_PREFIX', '/tmp/mpvsocket-')
PLAYER = (os.environ.get('SP_PLAYER', 'ipc') or 'ipc').strip().lower()
if PLAYER not in ('classic', 'ipc'):
    PLAYER = 'ipc'


def mpv_socket(kind):
    """IPC endpoint of the `kind` (music|video) mpv: a unix socket on Linux,
    the same name as a named pipe on Windows."""
    if os.name == 'nt':
        return r'\\.\pipe\mpvsocket-' + kind
    return MPV_SOCKET_PREFIX + kind


def load_or_create_secret(filename, env_var=None):
    """`env_var` wins; otherwise generate a random key once and persist it to
    the instance dir (0600). Sessions/tokens survive restarts; no shared
    default. Same derivation the Flask app used for instance/secret_key, which
    matters: OBS browser-source tokens are HMACs of that file."""
    if env_var:
        env_key = os.environ.get(env_var)
        if env_key:
            return env_key
    key_path = os.path.join(INSTANCE_DIR, filename)
    try:
        with open(key_path) as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    import secrets as _secrets
    key = _secrets.token_hex(32)
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        with open(key_path, 'w') as f:
            f.write(key)
        os.chmod(key_path, 0o600)
    except OSError as e:
        print(f'Could not persist {filename} (tokens reset each restart):', e)
    return key


SECRET_KEY = load_or_create_secret('secret_key', 'SECRET_KEY')
JWT_SECRET = load_or_create_secret('jwt_secret', 'JWT_SECRET')

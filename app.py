"""FastAPI application factory. Importing this module has NO side effects
(no schema sync, no workers) — ws.py / tests do that explicitly."""
import logging
import mimetypes
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import core.config as config
import core.db as _db
import core.events as events
from security.deps import ApiError

log = logging.getLogger('sceneplay')

# Serve .xpi with the type Firefox expects for its one-click install prompt.
mimetypes.add_type('application/x-xpinstall', '.xpi')
mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('text/javascript', '.mjs')

# Prefixes that are never the SPA shell (API, files, preserved contracts, overlays).
_NOT_SPA = ('/api', '/static', '/ttrpg/obs/', '/assets/', '/backups/', '/handouts/',
            '/activatescenes', '/receive_led_patterns', '/isAlive', '/killqueue',
            '/nextsong', '/nextvideo', '/set_volume', '/processyt', '/favicon.ico',
            '/music_', '/video_', '/updateWLEDSupport', '/docs', '/openapi.json', '/redoc')
_SPA_OK_FILE_PREFIXES = ('/handouts/', '/ttrpg/obs/feed/')   # SPA views under a non-SPA prefix


class DbSessionMiddleware:
    """Pure ASGI: one scoped session per request, removed when the response
    is done (streaming responses included)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        token = _db.begin_request_scope()
        try:
            await self.app(scope, receive, send)
        finally:
            _db.end_request_scope(token)


class CacheHeadersMiddleware:
    """Remote-portal rule: the shell/code revalidates on every load (ETag ->
    304 when unchanged); vendor bundles cache for a day."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        path = scope.get('path', '')
        policy = None
        if path.startswith('/ttrpg/obs/') and not path.startswith('/ttrpg/obs/feed/'):
            # OBS browser sources poll live state and token-gated renders:
            # nothing there may ever be cached (routes/obs.py's after_request).
            policy = b'no-store, no-cache, must-revalidate, max-age=0'
        elif path.startswith('/vendor/') or path in ('/shared/three.min.js', '/shared/Tone.js'):
            policy = b'public, max-age=86400'
        elif path == '/' or path.endswith(('.html', '.js', '.mjs', '.css')) or not os.path.splitext(path)[1]:
            if not path.startswith('/static/uploads'):
                policy = b'no-cache, must-revalidate'

        async def _send(message):
            if policy and message['type'] == 'http.response.start':
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'cache-control']
                headers.append((b'cache-control', policy))
                message['headers'] = headers
            await send(message)

        await self.app(scope, receive, _send)


def _error(status, message, code=None, detail=None):
    body = {'error': message, 'code': code, 'detail': detail}
    return JSONResponse(body, status_code=status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import anyio
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = 64
    except Exception:
        pass
    hub = events.EventHub()
    await hub.start()
    app.state.hub = hub
    if config.INTEGRATIONS and not getattr(app.state, 'testing', False):
        import core.boot as boot
        boot.start_integrations()
    try:
        yield
    finally:
        await hub.stop()
        if config.INTEGRATIONS and not getattr(app.state, 'testing', False):
            import core.boot as boot
            boot.stop_integrations()


def create_app(testing=False):
    from version import __version__
    app = FastAPI(title='ScenePlay', version=__version__, lifespan=lifespan,
                  docs_url='/docs', redoc_url=None)
    app.state.testing = testing

    app.add_middleware(CacheHeadersMiddleware)
    app.add_middleware(DbSessionMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=['*'],
                       allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'], allow_headers=['*'])

    # ── error envelope ──
    @app.exception_handler(ApiError)
    async def _api_error(request, exc: ApiError):
        return _error(exc.status_code, exc.message, exc.code, exc.detail)

    @app.exception_handler(_db._NotFound)
    async def _not_found(request, exc):
        return _error(404, str(exc) or 'not found', 'not_found')

    @app.exception_handler(HTTPException)
    async def _http_error(request, exc: HTTPException):
        detail = exc.detail
        msg = detail if isinstance(detail, str) else (detail or {}).get('error') if isinstance(detail, dict) else str(detail)
        return _error(exc.status_code, msg or 'error', None, detail if not isinstance(detail, str) else None)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request, exc: RequestValidationError):
        from fastapi.encoders import jsonable_encoder
        return _error(422, 'invalid request', 'validation', jsonable_encoder(exc.errors(), custom_encoder={Exception: str}))

    # ── routers ──
    from routers import auth, events as events_router, public, users
    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(events_router.router)
    _include_optional(app, 'routers.scenes')
    _include_optional(app, 'routers.utilities')
    _include_optional(app, 'routers.tables')
    _include_optional(app, 'routers.ttrpg')
    _include_optional(app, 'routers.monsters')
    _include_optional(app, 'routers.reference')
    _include_optional(app, 'routers.battlemap')
    _include_optional(app, 'routers.textures')
    _include_optional(app, 'routers.ai')
    _include_optional(app, 'routers.handouts')
    _include_optional(app, 'routers.relay_admin')
    _include_optional(app, 'routers.obs')

    @app.get('/api/v1/health')
    async def health():
        import sqlite3
        journal_mode = None
        try:
            conn = sqlite3.connect(config.DB_PATH, timeout=2)
            journal_mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
            conn.close()
        except Exception:
            pass
        return {'ok': True, 'journal_mode': journal_mode, 'pid': os.getpid()}

    # ── static + SPA ──
    app.mount('/static', StaticFiles(directory=config.STATIC_DIR), name='static')
    if os.path.isdir(config.WEB_DIR):
        for sub in ('app', 'shared', 'vendor', 'legacy', 'css', 'obs'):
            d = os.path.join(config.WEB_DIR, sub)
            if os.path.isdir(d):
                app.mount('/' + sub, StaticFiles(directory=d), name='web-' + sub)

        index = os.path.join(config.WEB_DIR, 'index.html')

        @app.get('/{path:path}', include_in_schema=False)
        async def spa(path: str, request: Request):
            p = '/' + path
            if os.path.isfile(os.path.join(config.WEB_DIR, path)) and path:
                return FileResponse(os.path.join(config.WEB_DIR, path))
            if p.startswith(_NOT_SPA) and not p.startswith(_SPA_OK_FILE_PREFIXES):
                return _error(404, 'not found', 'not_found')
            accept = request.headers.get('accept', '')
            if 'text/html' not in accept and accept not in ('', '*/*'):
                return _error(404, 'not found', 'not_found')
            if os.path.isfile(index):
                return FileResponse(index, media_type='text/html')
            return _error(404, 'SPA not built', 'not_found')

    return app


def _include_optional(app, modname):
    """Routers that arrive in later port phases."""
    import importlib
    try:
        mod = importlib.import_module(modname)
    except ModuleNotFoundError as exc:
        if exc.name == modname or (exc.name and modname.startswith(exc.name)):
            return
        raise
    for name in ('open_router', 'router'):
        r = getattr(mod, name, None)
        if r is not None:
            app.include_router(r)


app = create_app()

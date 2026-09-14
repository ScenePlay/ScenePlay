# Porting guide — Flask blueprint → FastAPI router + SPA view

This tree (`dev/ScenePlay`) is the FastAPI + single-page port of `dev/ScenePlay_Flask_Media_Wrapper`
(read-only reference: NEVER edit the Flask tree). Phases P0–P4 are done (auth, media tables, utilities,
library pages, TTRPG core, battle maps/textures/AI). This document is the contract every remaining
phase (P5 reference/monsters/handouts, P6 relay, P7 OBS, P8 LED/WLED/cron/servers) follows.

## Hard rules
- Never `git push`; never commit unless Eric asks. Never edit the Flask tree.
- The same `ScenePlay.db` must open in place: no new columns, no new Alembic revisions.
- Every path a session-less consumer hits stays VERBATIM (cron curl, browser extensions, other boxes,
  OBS browser sources with `?t=` HMAC tokens, watchdog `/isAlive`). Grid `/api/<table>*` and
  `/ttrpg/...` JSON paths also stay verbatim. Only `render_template` pages become
  `GET /api/v1/<page>` page-data endpoints (return the old template context as JSON).
- Windows + Linux parity; secrets only under `instance/` (never logged/rendered).
- Never touch the live box: dev instances run on their own port with a DB COPY.

## Backend conventions (see routers/ttrpg.py and routers/battlemap.py as the reference ports)
- One module per blueprint in `routers/<name>.py`. Define `router = APIRouter(prefix=<blueprint url_prefix>)`
  and, for `/api/v1` page-data endpoints, `api = APIRouter(prefix='/api/v1/...')` plus `open_router = api`.
  `app.py::_include_optional` mounts `router` and `open_router` automatically (already listed for
  routers.monsters/reference/handouts/relay_admin/obs; check the list in `create_app`).
- Endpoints are plain `def` (threadpool). `async def` only for SSE.
- Auth: `from security.deps import require_user, require_dm, get_current_user, sceneplay_dm_gate, ApiError,
  signed_url, require_dm_or_signed`. `login_required` → `user=Depends(require_user)`; `dm_required` →
  `Depends(require_dm)` (a 403 JSON `{"error","code":"dm_required"}`, NOT a 302). DM-only-ScenePlay pages
  (media side) use `Depends(sceneplay_dm_gate)`. `abort(404)` / `get_or_404` raise a 404 JSON envelope.
- Bodies: `data: dict = Depends(json_body)` (JSON), `form: dict = Depends(form_or_json)` (form OR JSON, files
  excluded), uploads as `name: UploadFile = File(None)` (read with `.file.read()`; `save_upload_downscaled`
  in routers/_util.py accepts an UploadFile). Query params are typed function args.
- Responses: `jsonify(x)` → `return x`; `jsonify(x), 4xx` → `JSONResponse(x, status_code=4xx)`;
  `redirect`+`flash` → `{'ok': True, 'message': '...'}` (the SPA toasts it).
- `url_for('static', filename=...)` → `core.urls.static_url(filename, external=False)`; `_external=True` →
  `external=True` (uses `urls.lan_base()`). `current_app.root_path` → `config.ROOT`; uploads →
  `config.UPLOADS_DIR`; `current_app.secret_key` → `config.SECRET_KEY`; `with app.app_context():` in
  threads → `with db.session_scope():` (import `core.db as _dbmod`; `_dbmod.session_scope()`).
- `from extensions import db` → `from core.db import db` (same surface: `db.Model`, `Model.query`, `db.session`,
  `db.func`). `from routes.auth import ...` → `security.deps`. `from routes._util import _now` →
  `routers._util`. Cross-router imports: `from routers.battlemap import _push_map_state` etc.
- Live updates: `core.events.emit(topic, payload)` after mutations. Topic names are pinned in `events.TOPICS`
  / `web/app/topics.js` (nowplaying, queue, health, relay, obs, downloads, update, netscan, dice, scene,
  server + parameterised battlemap:<id>, session:<id>, character:<id>, syncjob:<job>, aijob:<id>).
  Background sync jobs (reference/monsters) emit `syncjob:<job>` progress and use `db.session_scope()`.
- Settings: `sql.appsettingGet/appsettingSet` (raw sqlite on `sql.database`).
- Layout (since the reorganisation): shared modules live in `core/`, `media/`, `ttrpg/`, `integrations/`, `lighting/`, `ops/` — see CLAUDE.md; import them absolutely (`import core.config as config`).
- OBS/relay seams: `appctx.ctx` replaces the Flask app object handed to relay_ws/discovery/obs;
  `lan_base()` from urls.py; OBS `t=` tokens are HMACs of `config.SECRET_KEY` (keep the exact derivation
  from routes/obs.py). `_obs_poll_state` in routers/battlemap.py and `session_page` in routers/ttrpg.py already
  `try: from routers.obs import scene_link_map, scene_links_live, map_mode, viewed_character_id, CUT_TARGETS,
  _cut_scene_name, _muted_ids, auto_cam_on, _card_overrides, _ordered_party` — keep those names.

## Frontend conventions (web/app)
- Views are ES modules exporting `title` (string or `ctx => string`) and `async mount(outlet, ctx)`.
  `ctx = {params, query, path, navigate, reload, on(target, ev, fn), every(ms, fn), after(ms, fn),
  subscribe(topic, handler, {fallback:{every, fetch}}), watch(storeKey, fn), cleanup(fn), signal}` — all
  listeners/timers registered through ctx are torn down on unmount.
- Routes live in `web/app/routes.js` (already contain every old Flask page path; placeholder views re-export
  `coming.js` — replace the placeholder file, don't add routes unless a page is genuinely missing).
- Markup: `import { html, raw, render, esc } from '../../lib/dom.js'` — `html` escapes interpolations,
  `raw()` for trusted HTML, arrays are joined. `api.get/post/upload/del` from `api.js` (bearer added, errors
  toasted unless `{quiet:true}`, `ApiError` has `.status/.code`). `toast` from `ui/toast.js`. Plain
  `fetch('/...')` in ported scripts works too (lib/fetch_shim.js adds the bearer).
- Same-origin `<a href>` clicks are routed in-app; add `data-native` (downloads, `target=_blank` files).
- Legacy classic scripts live in `web/legacy/` (texture_picker, asset_picker, ai_generate, paste_image,
  portrait_prompt, floorplan_prompt, sfx-control, handout_reader, battlemap_fp) and shared ones in
  `web/shared/` (Tone.js, dice.js, sfx.js, three.min.js, battlemap3d.js). Load with
  `loadScript/loadScripts` from `lib/loader.js` (deduped). Never reference `static/scripts/`.
- Big pages ("legacy wrap"): write `template.js` (`render(d)` from page data) + generate `<page>.js` from the
  verbatim Flask script with a generator like `scripts/wrap_sheet_js.py` / `scripts/wrap_battlemap_js.py`:
  body wrapped in `export function init(ctx, d, G)`, `document.addEventListener(` → `ctx.on(document, `,
  `location.reload()` → `ctx.reload()`, `setInterval` → `ctx.every`, polls → `ctx.subscribe(topic, ...)`
  with the old poll as fallback, every top-level function exposed with `exposeGlobals({...})` (lib/legacy.js)
  for `onclick=""` attributes and un-exposed in the returned cleanup. Jinja `{{ x | tojson }}` → `G.X`.
  `url_for(...)` → literal paths. Old form+redirect `<form method=POST>` → `<form data-api="/path">` handled
  in index.js (see views/ttrpg/battlemap_manage/index.js).
- Bootstrap modals: `bootstrap.Modal.getOrCreateInstance(el)`; dispose + remove `.modal-backdrop` on cleanup.
- Cache-busted per-mount reload of self-wiring IIFE scripts: `loadScript(SFX_CTRL + '?m=' + n)`.
- `tests/test_web_assets.py` must stay green: every `import`/`loadScript` literal resolves, and no
  `url_for(`, `{{ `, `{% `, `static/scripts/` strings anywhere under `web/`.

## Tests (tests/conftest.py)
- Session `client` (TestClient over `create_app(testing=True)`) on a fully migrated temp DB; `dm`, `player`,
  `dm_token`, `player_token`, `auth(token)` header helper; `_make_user(username, role)`.
- `app` fixture = scratch DB (models + raw tables) bound for the test; `legacy_app` = `LegacyApp` whose
  `.test_client(user=dm)` returns a Flask-style client (`get/post/delete(path, json=, data=, files=)`,
  responses have `.get_json()`, `.get_data(as_text=True)`, `.status_code`). Old Flask route tests port by
  replacing their Flask-app fixture with `legacy_app` (see tests/test_dcc_sheet.py, tests/test_textures.py,
  tests/test_ai_routes.py): drop `with a.app_context():`, `302` for dm_required → `403`, multipart tuples →
  `files={'field': ('name.png', fileobj, 'image/png')}`, `routes.x` → `routers.x`, `REPO`-relative upload
  folders → absolute `tmp_path` folders (monkeypatch `UPLOAD_FOLDER` to `str(tmp_path / 'x')`).
- Tests for unported routers use `pytest.importorskip('routers.<name>')` so they turn on when the router lands.
- Run: `.venv/bin/python -m pytest tests/<files> -q -p no:warnings`; lint: `.venv/bin/ruff check .`;
  JS syntax: `node --check <file>`. Full suite: `pytest tests -q --continue-on-collection-errors`.
- Playwright smoke: `scripts/spa_smoke.py http://127.0.0.1:<port> yllonnoce x /path ...` (chromium installed).

## Dev instance (never the live box)
```
S=/tmp/claude-1000/-mnt-Transfer-5FD1E1415AC80F29-dev-ScenePlay/b91d6985-240b-4e12-9b7d-c91b484fbe44/scratchpad
cp $S/live/real.db /tmp/mydev.db          # DM login on that copy: yllonnoce / x
SP_PORT=<your port> SP_WORKERS=0 SP_INTEGRATIONS=0 SP_CRON_APPLY=0 SP_DB_PATH=/tmp/mydev.db \
  SP_MPV_SOCKET_PREFIX=/tmp/mpvsocket-dev- nohup .venv/bin/python ws.py --no-workers > /tmp/mydev.log 2>&1 &
```
Kill with `for p in $(pgrep -f "[w]s.py --no-w.*"); do kill $p; done` only for YOUR port (check `ss -ltnp`);
the app always runs on 8086 (SP_PORT); a second instance on the same box is refused at boot.

# External contracts frozen by the port

Every consumer that talks to ScenePlay without a browser session keeps its exact URL, method,
auth class and response shape. `tests/test_contracts.py` (+ `test_dm_only_gate.py`,
`test_open_endpoints_unauth.py` where present) pins these; add a row here whenever a new one appears.

| Consumer | Calls | Auth | Notes |
|---|---|---|---|
| Cron / Task Scheduler (`routers/tables/cron_schedule.py`, `defaultData/tblCronSchedule.json`) | `GET/POST /activatescenes/?id=N` (trailing slash), `POST /killqueue` (sync, ~5 s), `POST /set_volume {volume}`, `GET /api/keepmusicplaying/on\|off` (mutating GET), `POST /api/applycronschedules` | open (applycronschedules: DM) | base URL built from `SP_PORT`; `SP_CRON_APPLY=0` keeps dev instances out of the real crontab |
| Browser extensions (`ChromeExt/`, `FireFoxExt/`; the signed `.xpi` cannot change) | `GET /api/server-info` → `{app, server_name, version, os, machine, cores, capabilities{led, relay}}`, `GET /api/scenes` → `{"data":[...]}` (open even under DM-only), `POST /api/ChromeExtensionAddVideo {url, flname, mediaType, scene_ID}`, `/static/ext/*.xpi` as `application/x-xpinstall` | open + CORS `*` | |
| Other ScenePlay boxes / LAN | `GET /api/server-info` (discovery), `POST /receive_led_patterns {patterns}` + `OPTIONS` answering `Access-Control-Allow-Private-Network: true` | open | WLED and OBS are outbound only |
| Loopback | watchdog `GET /isAlive` → `{"isAlive":"true","pid","WatchManage"}` (`pid` is the single uvicorn process), `scene_end.py` → `POST 127.0.0.1:<SP_PORT>/api/lights-off`, `app_update.restart_app` (`os._exit`; Windows spawns `startApp.bat`), `ledPlayer` runs `sudo python3 <repo>/led_Run.py` | open | entry point keeps the name `ws.py` (watchdog / uninstall pkill patterns) |
| OBS browser sources (URLs stored inside OBS scene collections) | `/ttrpg/obs/card/<id>[/state]?t=`, `/card/dm[/state]`, `/tile/<id>`, `/tile/dm`, `/panel[/state]`, `/map[/state\|/floorplan\|/textures]`, `/static/uploads/obs/*`, `/assets/media/video/<id>.<ext>` (Range) ; `/ttrpg/obs/feed/<id>` (login) | HMAC `t=` of `instance/secret_key` | derivation unchanged; overlays keep polling `/state` (no SSE inside OBS's CEF); `reload-sources` is the one-click repair; every response `Cache-Control: no-store` |
| Remote portal (`../ScenePlayRemote`) | local→remote push/WS endpoints (`relay_broadcaster.py`, `relay_ws.py`, unchanged); remote→local fallback `GET /static/uploads/{battlemaps,portraits}/*` by absolute URL; `POST /ttrpg/relay/api/auth/verify`, `GET /ttrpg/relay/api/session/info` (`X-Relay-Secret`, legacy — no current caller); remote producer console: `producer_state` / `producer_frame` / `producer_ack` frames up the GM WebSocket, `producer_presence` / `producer_command` down it (also `pending_producer_commands` in `/sync` and the hello), users push carries `role` — see docs/superpowers/specs/2026-09-18-remote-producer-console-design.md | — | absolute URLs come from `urls.lan_base()`; the remote's dev quirk of reading `../ScenePlay/ScenePlay.db` read-only now resolves to THIS tree |
| Grid / JSON front-ends | every `/api/<table>*` grid endpoint and every `/ttrpg/...` JSON endpoint keeps its Flask path and shape | JWT bearer (`sceneplay_dm_gate` on media routes when DM-only is on; `require_user`/`require_dm` on TTRPG) | only `render_template` pages moved, to `GET /api/v1/<page>` |
| SPA deep links | every old Flask page path renders the SPA shell (`/ttrpg/character/<id>?dice=1`, `/handouts/<id>/read?page=`, `/backups/<name>` is a signed download) | JWT in the browser | `web/restarting.html` standalone |

## Auth classes
- **open**: no user, no DM-only gate.
- **JWT bearer**: `Authorization: Bearer <token>` (HS256, `instance/jwt_secret`; `?token=` accepted only by `GET /api/v1/events`).
  Errors are `{"error": msg, "code": login_required|dm_required|sceneplay_locked|validation|not_found|forbidden|..., "detail": ...}` — 401/403 JSON, never a 302.
- **signed URL**: `security.deps.signed_url(path)` (HMAC of `instance/secret_key`, 10 min) for downloads (handout PDFs, backups, asset files) so the JWT never lands in a URL.
- **OBS token**: `t=` HMAC of `instance/secret_key` per overlay, unchanged from 1.x.

## Live updates
`GET /api/v1/events?topics=a,b&token=&last_id=` (SSE). Topics: `nowplaying`, `queue`, `health`, `relay`, `obs`,
`downloads`, `update`, `netscan`, `dice`, `scene`, `server`, and parameterised `battlemap:<id>`, `session:<id>`,
`character:<id>`, `syncjob:<job>`, `aijob:<id>`. Every old poll endpoint still exists and is the SPA's fallback.
Events are written to `tblEvents` (created with `CREATE TABLE IF NOT EXISTS`, excluded from backup merge) so any
process can `events.emit()`.

# Producer console — core (design)

Date: 2026-09-14. Status: approved; implementation plan at docs/superpowers/plans/2026-09-14-producer-console-core.md.

## Why

ScenePlay already controls OBS from the Broadcast page (cuts, closeups, map mode, audio, outputs,
YouTube), but that page mixes configuration with live control and assumes the DM is the operator.
Streamed sessions want a second person — a producer on their own laptop, on the LAN or remote —
running the show through the ScenePlay website while the DM runs the table. This spec covers the
**console core**: the live surface. Three follow-ups build on it and get their own specs:
live content (overlay layer, reveal scene, lower thirds, ticker; library / upload / paste / AI
sources), the rundown (cues arming shot + content + ScenePlay scene), and producer-to-DM talkback.

## Decisions taken

| Question | Decision |
|---|---|
| Who | A separate producer on a second laptop, LAN or remote, via the ScenePlay site. |
| Access | Any DM login. No new role. |
| Switching | Preview / Program with Take, via OBS Studio Mode. Take uses the Broadcast page's transition and duration (changed 2026-09-15: the AUTO fade button and the console's own transition picker were removed; the map view AUTO / 2D / 3D toggle from the battle map sits there instead). |
| Monitoring | Snapshot multiview from obs-websocket screenshots (no video feed). |
| Live state to OBS | **State-driven**: one transparent browser overlay per scene, polling a state endpoint (like the panel and cards). No per-action OBS sources. The overlay itself ships with the *live content* phase; the core reserves the state shape and the nested-source Build step. |
| Storage | Follow the panel-notes idiom (real tables + Alembic) when a table is needed. The core needs none: countdown and marker notes are `tblAppSettings` keys with the `:s<session_id>` suffix already used by OBS art. |
| Extras in v1 | Audio mixer strip, clocks and countdown, hotkeys, record markers. Talkback is its own phase but the layout reserves its slot. |

## Layout

Route `/ttrpg/producer` (SPA view `web/app/views/ttrpg/producer/`), DM-gated, ttrpg layout with the
nav reduced to a slim strip. Designed for a laptop at 1366 px and up, side by side with the stream;
usable at 1024 px with the strip rows wrapping.

```
┌───────────────────────────┬──────────────────────────┬────────────────┐
│ PREVIEW (armed)           │ PROGRAM (live)  ● LIVE   │ Stream / Rec   │
│ snapshot 2 fps            │ snapshot 2 fps           │ health, clock, │
│                           │                          │ countdown, ⚑   │
├───────────────────────────┴──────────────────────────┤ markers,       │
│ SHOTS  [Party][Map][Carl][Donut][Mira]…[DM][Pre][Break][Post]  ← arm  │ (talkback slot)│
│ [ TAKE ▶ Fade 300ms ]   [ AUTO | 2D | 3D ]                            │
├──────────────────────────────────────┬────────────────────────────────┤
│ SCENEPLAY  active: <scene> ▸         │ AUDIO  Carl ▮▮▮ M  Donut ▮▮ M  │
│ [scene tiles, colour + LED swatch]   │ DM ▮▮▮▮ M  Music ▮▮ ⏭ ⏹ vol ─● │
│ [Skip][Kill][Lights off]             │ [MUTE ALL BUT DM]              │
└──────────────────────────────────────┴────────────────────────────────┘
(row 5, reserved: content + rundown from the later phases)
```

Shot tiles carry a small thumbnail from the snapshot loop and a tally border: green = in Preview,
red = in Program. Shot keys are the existing cut targets (`party`, `map`, `pre`, `intermission`,
`post`, `dm`, one per on-stream character) resolved through `_cut_scene_name` / `_scene_name_for`.

## Switching

- Opening the console enables OBS Studio Mode (`SetStudioModeEnabled true`); the server turns it
  off when the last console subscription ends (grace 10 s) and never leaves it on across a restart.
- Arm = `SetCurrentPreviewScene`. Take = `TriggerStudioModeTransition` after setting the Broadcast
  page's saved transition and duration (`SetCurrentSceneTransition`, `SetCurrentSceneTransitionDuration`).
  Take with nothing armed is a no-op with a toast. The map view button posts an empty body to the
  Broadcast page's `/ttrpg/obs/api/map-mode`, which steps auto → 2D → 3D and releases a pinned character.
- Existing direct switches keep working unchanged: auto-cam, scene-linked cuts, Broadcast page
  cuts, `switch_scene` callers. They change Program directly (`SetCurrentProgramScene` is legal in
  Studio Mode). The Program tile shows who moved the shot — "producer", "broadcast page" or "automatic"
  (auto-cam, scene link, auto-return, group cuts) — from a `last_switch` tag `obs_ws.switch_scene`
  and the Take path record.
- Auto-cam keeps running while a console is open (changed 2026-09-15 at Eric's request; it was
  paused by default at first); a toggle on the console pauses it. Pausing is a setting (`obs_auto_cam_paused_by_producer`) so the watcher thread reads it
  cheaply; the watcher clears it when the last console leaves.

## Multiview

- Snapshots are **polled**, not streamed: `GET /ttrpg/producer/api/snap/{program|preview|<shot key>}`
  returns one 320 px JPEG (`GetSourceScreenshot`, quality 60, `Cache-Control: no-store`; 204 when OBS
  has nothing). The console refreshes Program and Preview twice a second and every shot tile every
  3 s, only while the tab is visible. Base64 frames never touch `tblEvents`.
- Audio levels are polled the same way (`GET …/levels`, 4 Hz) from the `InputVolumeMeters` event
  stream, which the server subscribes to (obs-websocket `Reidentify`) only while a console is open.
- Console presence: `POST …/session` opens a console and returns an id; the page pings every 15 s;
  a console is dropped after 45 s without a ping or on `DELETE …/session/{id}`.
- Budget: roughly 20 KB per Program/Preview frame → ~80 KB/s per console. Fine on LAN and remote.
- Three consecutive failed frames drop the monitor refresh to 1 fps until one succeeds.

## Strip and extras

- **Audio.** Per-feed mute and the DM mute reuse `POST /ttrpg/obs/api/mute`; per-scene audio rules
  reuse `/api/scene-audio`. Levels come from obs-websocket `InputVolumeMeters` (subscribed only while
  a console is open) and are polled by the console at 4 Hz from `GET …/levels`. Music: the player bar's session-less calls (`/set_volume`,
  `/nextsong`, `/killqueue`, `/music_stopstart`) and `nowplaying` for the title. "Mute all but DM"
  = existing `{all:true, muted:true}`.
- **ScenePlay scenes.** Tiles from `GET /api/scenes` (colour, LED pattern name); click posts
  `/activatescenes/?id=`; Skip / Kill / Lights-off reuse the existing session-less paths. Active
  scene from the `queue` topic's `scene_states`.
- **Clocks.** Session clock = now − active session's `started_at` (falls back to console open
  time). Countdown: `POST …/api/countdown {seconds|until|clear}` stored as
  `producer_countdown_until:s<id>`; shown on the console and, in the later content phase, on the
  intermission overlay.
- **Markers.** `POST …/api/marker {note}`: when recording, `CreateRecordChapter` with the note as
  chapter name; always append `{at, note, recording}` to `producer_markers:s<id>` (JSON list,
  capped at 200) so the list survives when OBS is not recording.
- **Hotkeys** (client only, ignored while an input has focus): `1`–`9` arm shots in tile order,
  `Enter` Take, `V` map view, `M` mute all but DM, `K` marker, `Esc` clears the armed shot.

## Backend

- `routers/producer.py`, prefix `/ttrpg/producer/api`, `require_dm` on every route; registered
  in `app.py` after the OBS router. Endpoints: `session` (POST open / ping / DELETE close),
  `state` (GET: studio mode, program, preview, shots with scene names, transitions, recording /
  streaming, auto-cam paused, map mode, countdown, markers, console count), `arm`, `take`,
  `auto-cam-pause`, `countdown`, `marker`, `markers` (GET).
- `integrations/obs_ws.py` gains `studio_mode(enabled)`, `preview_scene()/set_preview_scene()`,
  `trigger_transition()`, `set_transition(name, ms)`, `record_chapter(name)`, `screenshot(source,
  width, fmt, quality)` (wrapping the existing raw call used by the dark-camera probe), and an
  `InputVolumeMeters` subscription toggle.
- `core/events.py` `TOPICS` and `web/app/topics.js` gain `producer`. One console event kind,
  `state`: emitted on any change to the state document above (the console re-fetches it).
- No new tables, columns or Alembic revisions in this phase.

## Frontend

- `web/app/views/ttrpg/producer/{index,template,console}.js` + `web/css/views/producer.css`.
  Plain ES modules, no legacy wrap. `index.js` loads state, opens the session, subscribes to
  `producer`, `obs`, `queue`, `nowplaying`; `unmount` closes the session and unsubscribes.
- `routes.js`: `/ttrpg/producer` → auth `dm`, layout `ttrpg`, bodyClass `producer` (nav strip).
- The Broadcast page gets one link: "Open producer console".

## Error handling

- OBS disconnected: red banner; every OBS-backed control disables. ScenePlay scene tiles and the
  music controls stay live (they do not need OBS).
- A failed obs-websocket request returns `{ok:false, error}`; the console toasts it and keeps the
  last state. Snapshot failures skip the frame; three consecutive failures drop to 1 fps until one
  succeeds.
- Two consoles at once are allowed; both see the same state; last action wins (as in OBS itself).
- Studio Mode left on by a crash: `obs_ws.start` checks `GetStudioModeEnabled` at connect and turns
  it off when no console is registered.

## Testing

- `tests/test_producer_api.py` on the legacy client with the `obs` stub fixture pattern from
  `tests/test_obs_output.py`: studio mode on at first session / off after the last closes (grace
  faked), arm → preview scene call, take → transition call, take with nothing armed, auto-cam
  paused while a console is open and cleared after, countdown set/clear, marker with and without
  recording (chapter call only when recording), snapshot loop starts on first subscriber and stops
  after the last, `state` document shape.
- `tests/test_events.py`: `producer` accepted by `/api/v1/events`.
- `tests/test_web_assets.py` keeps covering the new route and modules automatically.
- `scripts/spa_smoke.py`: open the console, arm by hotkey, Take, mute-all, marker, against the
  stubbed OBS state.

## Out of scope (later specs)

Live content (overlay page, reveal scene, lower thirds, ticker, sources), rundown and cues,
talkback, a video multiview, a producer role.

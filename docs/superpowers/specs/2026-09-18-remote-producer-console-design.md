# Remote producer console (design)

Date: 2026-09-18. Status: approved in conversation; implemented in the same piece of work in both
repos (this tree and `../ScenePlayRemote`).

## Why

The producer console (`/ttrpg/producer`, spec 2026-09-14) assumed the producer reaches the local
ScenePlay box directly. The relationship rules say remote users connect through the remote portal,
never to the LAN. This phase puts the console on the portal: local remains the only thing that
touches OBS, the DB and the players; remote stores nothing it computes and never calls local.

## Decisions taken

| Question | Decision |
|---|---|
| Scope | The full console: multiview, arm + Take, map view, ScenePlay scene tiles, audio mutes and faders, music, countdown, markers, auto-cam pause. |
| Who | Any local account with role `dm`, joining the portal with the normal code + username + password. |
| Transport | The existing GM WebSocket in both directions. State and frames go up; staged commands come down with an expiry. The `/sync` poll and the reconnect hello carry pending commands as a fallback. |
| Multiview | Program and Preview at 1 fps, each shot tile every 5 s, only while a remote console is open. Local keeps its own 2 fps. |
| Storage on remote | `producer_commands` table (remote's own schema). State and frames live in process memory only. |
| Storage on local | None. The dedup ledger is an appsettings key like the mutation ledger. |

## Contracts

### Users push (local → remote, `POST /session/{id}/users`)
Each entry gains `role` (`dm` | `player`, default `player`). Remote stores it in `session_users.role`.

### Join (`POST /join`)
Unchanged request. When the matched account (character owner or spectator account) has role `dm`,
the issued JWT keeps `scope: player` and adds `producer: true`. Every existing player endpoint keeps
working for that token; producer endpoints require the flag.

### GM WebSocket frames, local → remote
- `producer_state` `{payload: <state document>}` — the local `state_doc()` plus `audio_rows`
  (`[{name, character_id, muted, volume_db}]`), `music_volume_db`, `levels` (`{source: [peak..]}`),
  `music_volume` (the room player's 0–100). Sent on every local `_emit_state()`, on every OBS `obs`
  event and every 5 s as a heartbeat while a remote console is open (levels ride in it, so meters
  update at 5 s from remote; no separate meter stream).
- `producer_frame` `{payload: {target, jpeg_b64, ts}}` — target is `program`, `preview` or a shot
  key. Fire-and-forget; only the newest frame per target is ever in flight.

### GM WebSocket frames, remote → local
- `producer_presence` `{data: {consoles: n}}` — the number of open remote consoles. Sent on every
  change and inside the hello (`producer_consoles`).
- `producer_command` `{data: <command row>}` — a staged command; also replayed in the hello
  (`pending_producer_commands`) and in `GET /session/{id}/sync`.
- Local acks with a request `producer_ack` `{payload: {id, status, error}}` (HTTP fallback
  `POST /session/{id}/producer/ack`). Status: `applied` | `rejected` | `expired`.

### Command row
`{id, session_id, username, cmd, args (JSON), client_id, ttl_s, created_at, age_s, status}`.
`age_s` is computed by remote at emit time so local never compares clocks: a command is expired
when `age_s > ttl_s`. Default TTL 5 s for `arm` and `take`, 30 s otherwise; the portal may lower it.

Commands and the local functions they run:

| cmd | args | local |
|---|---|---|
| `arm` | `{key}` (empty clears) | `producer.arm(key)` |
| `take` | `{}` | `producer.take()` |
| `map_view` | `{}` or `{mode}` | `routers.obs.api_map_mode` core |
| `auto_cam_pause` | `{paused}` | `producer.set_auto_cam_pause` |
| `spotlight` | `{key}` | `producer.spotlight(key)` |
| `activate_scene` | `{scene_id}` | `routers.public._activate_scene` |
| `skip` / `kill` / `lights_off` | `{}` | the session-less endpoints' functions |
| `music_toggle` | `{}` | `mpv_command('music', 'cycle pause')` |
| `set_volume` | `{volume}` | `setvolume` |
| `mute` | `{character_id, muted}` or `{all, muted}` | `routers.obs.api_mute` core |
| `fader` | `{character_id \| target:'music', db}` | `routers.obs.api_volume` core |
| `countdown` | `{seconds} \| {clear}` | `producer.set_countdown` |
| `marker` | `{note}` | `producer.add_marker` |
| `clock_reset` | `{}` | `producer.clock_reset` |
| `markers_clear` | `{}` | `producer.clear_markers` |
| `barge` | `{on}` | `producer.set_barge` |
| `producer_profile` | `{name, icon}` | `producer.set_profile` (icon from the fixed `PRODUCER_ICONS` list) |
| `transition` | `{name, ms}` | `producer.set_transition_pref` |

### Remote HTTP surface (producer JWT)
- `POST /producer/console/open` → `{console_id}`; `POST /producer/console/ping {console_id}`;
  `DELETE /producer/console/{id}`. A console is dropped after 45 s without a ping. Any change in
  the count emits `producer_presence` to local.
- `GET /producer/state` — the last pushed state document, or 404 when local has not pushed one.
- `GET /producer/frame/{target}` — the last JPEG for the target (`Cache-Control: no-store`), 204 when none.
- `POST /producer/command {cmd, args, client_id, ttl_s}` → `{id, status: 'pending'}`.

### SSE (producer connections only)
`producer_state` (the document), `producer_ack` (`{id, client_id, status, error}`), `producer_frame_ts`
(`{target, ts}` so the page fetches only new frames). Non-producer connections never receive these.

## Local lifecycle
- `routers/producer.py` counts remote consoles (`set_remote_consoles(n)`) alongside local ones, so
  Studio Mode and the meter subscription follow the same open and idle rules.
- `integrations/relay_producer.py` owns: the push thread (state heartbeat, frames), `execute(row)`
  (dispatch + expiry + ledger), `link_down()` (remote consoles → 0 when the socket drops).
- Frames are taken with the same `obs_ws.screenshot` call the local console uses, from the push
  thread, and sent through `relay_ws.send_event`. Nothing is queued: a failed send is dropped.
- Everything in `relay_producer` swallows its own errors; the console feature must never break the
  relay link or local playback.

## Error handling
- OBS not connected: `arm`, `take`, `spotlight`, `mute`, `fader` ack `rejected` with the same text
  the local console shows. Settings-only commands (`map_view`, `countdown`, `marker`, `auto_cam_pause`,
  ScenePlay commands) still apply.
- Unknown `cmd` → `rejected`. Expired → `expired`, nothing runs.
- Remote marks the row with the ack status; a row still `pending` after 120 s is expired by remote's
  reaper so the hello never replays stale commands.

## Testing
- Remote: users push stores role; join issues the producer flag for DM only; producer endpoints
  reject non-producer tokens; command insert/emit/ack round trip over the GM socket; hello carries
  pending commands and console count; frame and state caches; SSE filtering.
- Local: users push carries role; `execute` dispatches, rejects, expires and dedups; presence updates
  the console count; the push thread only runs with remote consoles; relay_ws routes the new events.

## Out of scope
Talkback, rundown, live content overlays (their own specs). Producer faders and levels at higher
than the 5 s heartbeat rate.

# Producer console: next builds

Date: 2026-09-18. Source: `2026-09-18-producer-console-feature-research.md`, turned into five build tranches. Each tranche was planned against the code by one agent and attacked by a skeptic; the skeptics' corrections are folded in below and their effort numbers replace the planners'. Chat moderation is its own track: `2026-09-18-chat-moderation-brief.md`.

**How to use this**
- Builds are in the order the research recommends. Each is shippable on its own.
- Every build ends with a live-OBS acceptance pass (Linux and Windows) and tests in both repos.
- Rules that hold throughout: local is the only authority; remote stages commands with a TTL; no new tables or columns until the cut-over (settings keys with the `:s<id>` suffix); no Space, F-key or Ctrl+digit hotkeys.

**Order and effort (skeptic-adjusted)**

| # | Build | Effort | Why this order |
|---|---|---|---|
| 1 | Know the show is on air: stream health, outputs + recording safety, markers that export | 7–8 days | Fixes the frozen timecodes everything else leans on; persists the YouTube broadcast id |
| 2 | Never air a dead tile: feed health + repair menu + take guard, undo, CUT, on-air word + lock + rehearsal | 6–7 days | The switching safety net; pure-server fixes land first |
| 3 | Talk to the table: text cues both directions, talent tally | 5.5–6 days | Shares one relay branch; needs a small link-ready fix in relay_ws |
| 4 | Run the clock: FTB / stand-by, break + end-of-show macros, hard-out timer | 5.5–6.5 days | Macros need the output calls from Build 1 only for the file-path nicety |
| 5 | Polish the picture and the sound: reframe, hot-mic / dead-air alarms, music bed + duck, pre-flight | 8–9 days | Shared meter-owner refcount and new wrappers first |

**What the planners found the research got wrong** (already corrected in the sections)
- **Auto-cam never moves Program.** It only swaps a dark tile to its stat card. "Changed by auto-cam" cannot occur; the real movers are auto-return, the ScenePlay scene link, the Broadcast page and in-OBS clicks.
- **Shift+I and Shift+P are not free.** Both consoles uppercase the key and ignore Shift, so Shift+I arms intermission today. The arm test must add `!e.shiftKey` before any Shift macro ships.
- **The 5 s TTL "class" is two dicts plus an allowlist**: `TTL_DEFAULT_S` in `integrations/relay_producer.py`, `TTL_DEFAULT_S` and `COMMANDS` in the remote's `routers/producer.py`. Every new command touches all three or the remote 400s it.
- **`prev_scene` cannot come from the OBS event alone**: `switch_scene` writes `current_scene` optimistically first, so record it in `switch_scene` too.
- **CUT needs no new remote command**: `take` already honours `{transition:'Cut'}`. But `_ms()` treats 0 as unset, so skip the duration for Cut instead of sending 0.
- **`_sweep` is a Timer chain, not a worker**: a 5 s health poll needs its own daemon thread with an idle Event, the `relay_producer._push_loop` shape.
- **The `health` SSE topic already exists and carries campaign HP.** Stream health must not emit on it.
- **Disk space needs no local disk access**: `GetStats.availableDiskSpace` is measured on the OBS machine.
- **`obs_is_local()` exists** (the research listed it as missing).
- **Refresh-one-source has no endpoint today**; the repair menu is four commands, not three.
- **Benched members never appear in `shots()`** (`_ordered_party()` drops them), so a benched badge needs `include_offstage=True` in the shot builder.
- **Show scenes are `ScenePlay Pre` / `Intermission` / `Post`**, not `ScenePlay - X`; the black scene should be `ScenePlay Black` with an `obs_black_scene` override.
- **Remote cannot be atomic** and local is not transactional against OBS: a macro is one staged row run as one function on the single command thread, with step reporting.
- **Cue text needs a 200-char cap** (`set_profile` caps at 60) and a `cue: 60` / `cue_ack: 30` TTL entry on both sides; T is taken by Duo shot, so cues use Q / Shift+Q.
- **Marker rows have no `kind` or live timecode today**; new fields are additive and both painters keep working until updated.

---

## Build 1 — Know the show is on air

**Goal** — Give both producer consoles (local `/ttrpg/producer` and the portal mirror) a truthful picture of the outputs: stream/recording up, healthy, how far in, with safe start/stop/pause/split controls and markers that export as YouTube chapters or CSV. Fixes the frozen `stream_timecode`/`record_timecode` and persists the YouTube broadcast id every later YouTube feature needs.

**Effort** — 7–8 days (skeptic: the planner's 5 was ~40 % light). Dominated by two UIs each gaining hold-to-confirm, eight `obs_ws` wrappers, a poller thread with two thread-safety rules, and a live pass needing OBS ≥ 30.2, a replay-buffer profile, YouTube link and Windows. Split: **PR-A** (timecodes, poller, health, outputs, go-live persist, ≈3.5 d) then **PR-B** (pause/split, marker kinds, export, Clip, ≈3.5 d).

### What it does (per item)

#### 1a. Live output timecodes (bug fix)
- **`_handle_event` writes cache only**: `StreamStateChanged`/`RecordStateChanged` with `outputActive:false` clear the timecode and `*_duration_s`; `outputState` PAUSED/RESUMED sets `record_paused`; STOPPED stores `outputPath` (may be null) as `last_record_path`; `RecordFileChanged` (ws 5.5) updates it. Never SQLAlchemy on the reader thread.
- **Health poller** `_health_loop`: own daemon thread, blocks on an `Event` when `console_count()==0`, started lazily by `_ensure_health_thread()` from **both** `open_console` and `set_remote_consoles` (portal-only producers otherwise get nothing).
- **Tick** every `HEALTH_POLL_S=5` while `obs_ws.connected()` and any output is on; skips a tick if the previous is still running; each tick body inside `with db.session_scope():` with `request()` calls outside it.
- **`apply_output_status(stream, record)`** writes timecodes, durations, `streaming`/`recording`/`record_paused` (from `outputPaused`) under `_cache_lock`; **no `_notify`** except `_notify('output')` when a poll finds a change the events missed.
- **`state_doc`** adds `stream_duration_s`, `record_duration_s`, `record_paused`, `last_record_path`, `health_at`; `tickClocks()` on both consoles adds `since` to the record counter only when `!state.record_paused`.
- **Solo-DM decision needed**: either wake the poller whenever an output is active, or state in the spec that health is console-only.

#### 1b. Stream health pill + incident markers
- **`obs_ws.output_stats()`**: three `request()` calls (`GetStats`, `GetStreamStatus`, `GetRecordStatus`).
- **Window**: 60 s deque; `dropped_pct_1m` from **`GetStreamStatus`** skipped/total deltas (network); `encoder_lag_pct_1m` from `GetStats`'s pair (amber only, own reason text); render lag from `renderSkippedFrames`; discard samples whose totals went backwards.
- **Thresholds**: amber >0.5 % dropped or congestion >0.2; red >2 % dropped, `outputReconnecting`, or `disk_min_left` < 30 (`availableDiskSpace` ÷ `outputBytes` rate, `None` until two recording samples). `off` when no output runs.
- **Delivery**: `GET /ttrpg/producer/api/health` for curl/debug only; the local console paints the pill from `state.health` in `paintState` (no second 5 s poll); `producer` SSE emitted on level change only. The existing `health` topic is campaign HP — untouched.
- **Incident**: entering red appends one `{kind:'incident', note:'Stream: <reason>'}` marker, latched 60 s, no chapter.

#### 2a. Outputs row (hold-to-confirm)
- **Buttons** Start/Stop recording, Start/Stop streaming: 700 ms CSS fill, JS timer; `pointerup`/`pointercancel`/scroll cancels. Completion posts `POST /ttrpg/obs/api/output/{kind} {on}` — never a toggle.
- **Pills**: REC red recording, amber "REC off" while streaming without recording; STREAM red streaming. Disabled while `!state.connected`.
- **No hotkey** starts or stops an output.
- **Remote**: stages `output {kind,on}`; `_dispatch` coerces `args.get('on') is True`, rejects anything else.

#### 2b. Pause / resume / split, file path
- **Wrappers** `pause_record(paused)` and `split_record()`; endpoints `POST .../record/pause` and `.../record/split` (`require_dm`), refuse when not recording, relay `ObsRejected.comment` verbatim.
- **Version gate** `ws_at_least(5, 5)` (tuple compare, `''` = old); error text "Needs obs-websocket 5.5 (OBS 30.2 or newer) — this OBS runs <ws_version>"; button hidden when `state.obs.split_ok` is false.
- **Saved path**: poller notices `last_record_path` changed and persists `producer_last_record_path:s<id>`; console shows `Saved: <basename>` computed client-side with `path.split(/[\\/]/).pop()` — paths are on the OBS machine.

#### 2c. YouTube go-live + persist
- **Guard**: `api_yt_golive` returns 409 while `streaming` (the Broadcast page already shows `d.error`).
- **Persist** `yt_broadcast_id` and `yt_watch_url` with the `:s<id>` suffix after `go_live`, before `SetStreamServiceSettings`.
- **`state_doc.youtube`** `{linked, watch_url, broadcast_id, channel}` — never secrets. Hold-to-confirm button when linked and not streaming; watch link beside STREAM.

#### 3a. Markers grow up
- **`add_marker(note, kind='manual', extra=None, chapter=None)`**, `chapter` defaults to `kind=='manual'`; rows gain `kind`, `stream_timecode`, `streaming`, `path`.
- **Legacy rows**: `row.get('kind') or 'manual'`, missing `stream_timecode` falls back to record timecode — everywhere (export, both painters).
- **Take rows** go in their own ring `producer_takes:s<id>` (cap 100), merged only at export; `add_marker(emit=False)` so a Take emits once. State tail stays last 30 non-take rows.
- **Glyphs** ⚑ manual, ▶ take, ⚠ incident, ✂ clip on both consoles.

#### 3b. Copy chapters / CSV
- **`chapters_text(rows)`**: manual only; first line forced `00:00`; merge rows <10 s apart; pad to 3 lines; `H:MM:SS` over an hour; record timecode when stream is empty.
- **`csv_text(rows)`** via `csv` module; `GET .../markers/export?format=chapters|csv` returns `text/plain`.
- **Clipboard** with `<textarea>` fallback (downloads inert in the portal); remote gets `markers_export {chapters, csv}` in `build_state`, cached per markers change.

#### 3c. Clip (C)
- **`replay_buffer_active()`** catches `ObsRejected` (504 `OutputDisabled`) → `None` = not configured; `set_replay_buffer(on)` tolerates 500/501/504; `save_replay()` is async.
- **`POST .../clip`**: start buffer if needed, save, append pathless `clip` marker; poller patches `path` when it sees a new `last_replay_path` in cache, re-emits `producer`.
- **Auto-start** replay buffer once per output start, never stop it (OBS REPLAY indicator lights — document). `replay_configured` lives in a module dict, reset on idle/boot/`_on_obs_connected`.

### Files touched
- **Local**
  - `integrations/obs_ws.py`: `_blank_cache` fields, `_handle_event` branches, `_NOTIFY_EVENTS`, eight wrappers.
  - `routers/producer.py`: poller, window/thresholds/latch, five endpoints, `add_marker` changes, take ring, `chapters_text`/`csv_text`, `state_doc`, cleanup in `_off_if_idle`/`reset_after_restart`/`_on_obs_connected`.
  - `routers/obs/__init__.py`: `api_yt_golive` 409 + persist.
  - `integrations/relay_producer.py`: TTLs, `_dispatch` for five commands, `markers_export`.
  - `web/app/views/ttrpg/producer/{template,console,index}.js`, `web/css/views/producer.css`: pills, Outputs row, `holdToConfirm()`, glyphs, copy buttons; drop `/health` poll.
  - `docs/PORT_CONTRACTS.md`, both 2026-09-18 specs (marker shape, command table, compat rule).
- **Remote**
  - `routers/producer.py`: `COMMANDS` + `TTL_DEFAULT_S` for five commands.
  - `portal/producer.js`: HEALTH pill, Outputs row, Clip/C, copy buttons, glyphs, counters; feature-detect `state.health === undefined` and hide new UI.
  - `portal/style.css`: `.pc-pill.warn`, `.pc-hold`, `.pc-out`.
  - `tests/test_producer.py`.

### Contracts

| cmd | args | TTL s |
|---|---|---|
| `output` | `{kind:'stream'|'record', on:bool}` | 5 for `on:true`, 30 for `on:false` (`ttl_for` sees the row) |
| `record_pause` | `{paused:bool}` | 5 |
| `record_split` | `{}` | 5 |
| `clip` | `{note?}` | 5 |
| `yt_golive` | `{}` | 5 |
| `marker` (existing) | `{note}` — kind always `manual` | 30 |

| key | meaning |
|---|---|
| `producer_markers:s<id>` | existing; rows gain `kind`, `stream_timecode`, `streaming`, `path` |
| `producer_takes:s<id>` | take ring, cap 100 |
| `yt_broadcast_id:s<id>` / `yt_watch_url:s<id>` | set by `api_yt_golive`; bare key when no session |
| `producer_last_record_path:s<id>` | from STOPPED `outputPath` via the poller |
| `obs_last_error` | existing; rejections via `_record_error` |

| wrapper | obs-websocket request |
|---|---|
| `output_stats()` | `GetStats` + `GetStreamStatus` + `GetRecordStatus` |
| `apply_output_status()` | cache write, no request |
| `pause_record(paused)` | `PauseRecord` / `ResumeRecord` |
| `split_record()` | `SplitRecordFile` |
| `replay_buffer_active()` | `GetReplayBufferStatus` |
| `set_replay_buffer(on)` | `StartReplayBuffer` / `StopReplayBuffer` |
| `save_replay()` | `SaveReplayBuffer` |
| `ws_at_least(major, minor)` | none (`GetVersion` primed) |

- **C** — Clip, both consoles, gated on `state.connected`. No collision: the portal's other keydown handlers are one-shot autoplay arms.
- **No hotkey** for start/stop/pause/split/go-live.

### Tests
- `tests/test_obs_ws.py` → event branches set/clear cache fields; `apply_output_status` under lock; `ws_at_least(5,5)`; wrappers send the named requests; `set_replay_buffer` tolerance.
- `tests/test_producer_api.py::TestHealth` → `_health_from_window()` thresholds, one incident per red entry, backwards-totals discarded.
- `TestHealthPoller` → `_health_tick()` as a pure function; one thread test with `HEALTH_POLL_S` at 0.05 and `_health_stop` Event joined by `fresh`.
- `TestRecordControls`, `TestClip`, `TestMarkers` → refusals, rejection text verbatim, version gate, pathless-then-patched clip, legacy rows default to `manual`, `chapters_text`/`csv_text`, export formats.
- `tests/test_obs_session_art.py::TestGoLive` → 409 with `_cache['streaming']=True` under lock, persist with and without a session (beside the existing `dm_app`/`fake_golive`).
- `tests/test_relay_producer.py` → five dispatches, on/off TTL asymmetry, `'false'` string rejected, `build_state` has `health` and `markers_export`.
- `../ScenePlayRemote/tests/test_producer.py` → five commands accepted at 5.0, cap 60, unknown 400.

### Acceptance (check on a live OBS)
1. Recording: REC red, counter matches OBS within seconds; stop in OBS → pill drops, `Saved: <file>` appears.
2. Streaming, drop the RTMP leg 20 s (cable pull works only if OBS and ScenePlay share the box): amber → red within two polls, one ⚠ row even if the link flaps.
3. Stream only: REC amber "REC off". Release Start early → nothing; hold → recording. No key affects outputs.
4. OBS ≥ 30.2: Pause shows "REC ‖ paused", counter stops; Split → new file line. Older OBS: Split absent, API names the version.
5. YouTube linked: hold Go live → broadcast, watch link, `yt_broadcast_id:s<id>` in `tblAppSettings`; while streaming a direct POST is 409.
6. K ×3 within 10 s plus a take: chapters block starts `00:00`, merged line, ≥3 lines; paste into YouTube and chapters render.
7. Replay buffer on: C → ✂ row gains a path within a second. Off: error text, button greys.
8. Portal mirrors every pill/counter/path within 5 s; stale START acks `expired`; late STOP still lands.
9. Windows OBS path shown verbatim, basename correct.

### Risks and skeptic's corrections
- **Poller start** — plan started it only from `open_console`; portal-only producers would get nothing. Start from both entry points, gate ticks on `console_count()`.
- **Reader thread DB work** — plan patched markers/settings from the events listener, which runs on the obs-ws reader thread with no session scope. Cache-only there; the poller does DB work inside `session_scope()`.
- **Paused counter creep** — `tickClocks` adds `since` unconditionally; gate on `record_paused`, read `outputPaused` each poll.
- **Wrong frame counters** — `GetStats` pair is encoder lag, not network drops; use `GetStreamStatus` for `dropped_pct_1m`.
- **Version string** — 5.5 shipped with OBS 30.2, not 30.1; verify against the changelog before wording.
- **Replay 504** — `GetReplayBufferStatus` itself rejects when unconfigured; catch on the status read.
- **Take rows flooding the tail** — separate ring, single emit per Take.
- **STOP TTL** — a late stop is still wanted; asymmetric TTL, state it in the spec either way.
- **Double `/health` poll** — drop it; `state.health` rides the existing 5 s `/state` fetch.
- **Compat** — old local + new portal must feature-detect; old portal + new local ignores new keys safely.
- **Slow OBS** — three requests per tick behind 2 fps screenshots; skip overlapping ticks, swallow `ObsUnavailable`, no requests while disconnected.

---

## Build 2 — Never air a dead tile

**Goal** — The producer sees before pressing Enter whether the armed shot will show a face (dark / dropped / card / benched tiles dim and need a second Enter), can repair it from the tile, and is covered by a dark-fallback cut when nobody is watching. Every Program change not made by this console is named on the Program tag with a 10 s Undo; CUT, ON AIR word, LOCK and a rehearsal flag round it out, mirrored on the portal console.

**Effort** — 6–7 days (skeptic-adjusted from 5). Server half ~2.5 d; the overrun is the eight client features built twice (lit-style `html` locally, string innerHTML on the portal) plus a live-OBS pass for the transition re-assert and 'obs' attribution timing.

### What it does (per item)

#### 1a. Feed health fields on every shot
- **Player/DM shots gain** `feed` (`obs._feed_state`: live/ready/stale/nofeed), `dark` (in `obs._dark_ids`), `showing` ('card'|'camera'), `benched` (in `obs.offstage_ids()`); specials carry `None`/`False`.
- **`showing` uses a new shared helper** `obs._showing_card(char, presence, overrides)` — the `_tile_plan` rule (override, no video URL, in `_auto_dark_ids`, or stale). Skeptic: the `_mapping_rows` predicate is broken today (both URLs start with `_card_base()`), so this fix also repairs the Broadcast page.
- **Benched members are listed** via `_ordered_party(include_offstage=True)`, hotkey `''`, appended **after `SPECIALS_BACK`** so they are the tiles the portal's `TILE_MAX` cuts, not the post-show card.
- **`arm()` and `spotlight()` both refuse** benched keys (`.pc-spot` is reachable without arming); both consoles omit `.pc-spot` and Move up/down on benched tiles.
- **`state_doc.map_live`** from a new `obs.map_is_live()`, cached alongside shots (it is a `tblBattleMaps` query; not per `state_doc()` call).
- **`relay_producer._shot_keys()`** skips benched shots.

#### 1b. Dark scan decoupled from auto-cam
- **Two sets**: `_dark_ids` = what the scan saw; `_auto_dark_ids` = what tiles act on (drives `_tile_url`).
- **Scan condition** widens to `obs_ws.connected() and (auto_cam_setting() or producer.producer_active() or fallback_s > 0)`; late `import routers.producer` inside the function.
- **Three-state rule** (skeptic): `not auto_cam_setting()` → clear `_auto_dark_ids` always; setting on but producer-paused → freeze; `auto_cam_on()` → mirror.
- **On `_dark_ids` change**: `_emit('feed', dark=[...])` on the existing `obs` topic and `producer._invalidate_shots()`. No new SSE topic.
- **Cleanup**: `_dark_ids`, `_dark_since`, `_fallback_done` clear in the same branch that clears `_cam_dark_votes`.

#### 1c. Dim + double-Enter take guard
- **Tile class `dim`** + badge word ('dark' / 'dropped' / 'no feed' / 'card' / 'benched'); map tile dims with 'no map' when `map_live` is false.
- **Arming still arms**; toast "Carl's camera is dark — Enter again to take", `guard={key, at}`.
- **First Enter/Shift+Enter/TAKE/CUT** re-toasts and paints "TAKE — confirm"; second within **8 s** takes; new arm, Esc, or a portal 'rejected' ack clears it.
- **Pure client logic**, same in both consoles.

#### 1d. Per-tile repair menu (⋯)
- **Popover**: Refresh source (confirm: drops their mic a few seconds), Card on/off, Bench/Return, Move up/down (confirm: renumbers 1–9).
- **Refresh** → new `POST /ttrpg/producer/api/shot/refresh {key}` → `obs_ws.refresh_browser_source(obs._source_name_for(char))`.
- **Other three** call existing `/ttrpg/obs/api/card-override`, `/on-stream`, `/reorder`.
- **Every path calls `_invalidate_shots()`** after the routers.obs call (skeptic: otherwise the 2 s shots cache shows stale badges for up to 5 s).
- **Remote**: four staged commands dispatched via `_plain(api_card_override(args, None))` etc.

#### 1e. Dark fallback cut
- **Setting** `producer_fallback_s` (global, '0' = off); number input in the side card.
- **In the cam-watch tick**: Program == `_scene_name_for(char)`, dark ≥ N s, not in `_fallback_done`, rehearsal off → `obs_ws.switch_scene(party_scene_name(), by='fallback')`, `add_marker(..., kind='incident')`, `_emit('cut', by='fallback')`. Preview/`_armed` untouched.
- **`_dark_since` stamps at the first dark vote** (skeptic: two-pass confirm made real latency N+2…N+9 s). Tooltip states the honest timing.
- **Gated on the setting**, not `producer_active()`, so a solo DM on the Broadcast page gets it too.

#### 2a. `prev_scene` + honest attribution
- **`obs_ws._blank_cache`** gains `prev_scene`; `switch_scene`/`trigger_transition` record it.
- **Provisional tag written under `_cache_lock` BEFORE the request**, rolled back on `ObsRejected` (skeptic: the event can arrive before the caller writes the tag → false 'CHANGED BY OBS').
- **`_handle_event('CurrentProgramSceneChanged')`** tags `by='obs'` when `last_switch` is None, a different scene, or >5 s old; `SceneNameChanged` renames `prev_scene`.
- **`_unfeature(by='broadcast')`** as a parameter; only the auto-return timer passes `by='return'` (Group button keeps 'broadcast').
- **`by` vocabulary**: producer | broadcast | auto | return | fallback | obs.

#### 2b/2c. Undo + flash
- **`POST /ttrpg/producer/api/undo`** → `producer.undo()`: refuses when OBS down or `prev_scene` empty/== Program; else `set_preview_scene(prev)`, `_armed` = matching shot or None, `_take(...)`.
- **Program tag** flashes "CHANGED BY <label>" 3 s and offers UNDO 10 s when `last_switch.at` is newer and `by !== 'producer'`.
- **Suppress the flash** (keep '· by' suffix) for `by='broadcast'` when `consoles == 1` — a DM with both tabs open should not undo their own cuts.
- **Z works whenever `prev_scene` is set**; blocked by LOCK, guarded like Take.

#### 3. CUT (Shift+Enter)
- **Local** posts `/take {transition:'Cut'}`; remote stages `take {transition:'Cut'}` (TTL 5, no new command). Duration is skipped for Cut.
- **`take()` captures `saved = _saved_transition()` BEFORE `set_transition`** and passes it to `_take(transition, ms, saved)` (skeptic: evaluated after, the comparison is always equal and OBS sticks on Cut).
- **Re-assert** immediately for Cut, else via `_later(ms/1000 + 0.1, fn)` (module hook wrapping `threading.Timer`); the callback catches `ObsUnavailable`/`ObsRejected`.
- **Check `e.shiftKey` before the plain Enter branch** in both keydown handlers.

#### 4a/4b/4c. On-air word, LOCK, rehearsal
- **`#pc-onair`**: OFF AIR / ON AIR / ENDING (Program == post-show shot's scene), client-only.
- **L** toggles a per-tab lock: every other hotkey and Program-moving click ignored with toast; placed ahead of the `state.connected` gate so it works with OBS down. Kill queue / Rebuild confirm while ON AIR.
- **Rehearsal** `producer_rehearsal:s<id>`; `_take` logs `REHEARSAL: would take` and returns `{ok, rehearsal, scene}`; CUT and Undo inherit it; fallback skips.
- **Reset in a shared `_start_sitting_if_stale()`** used by `open_console` AND `set_remote_consoles` (skeptic: portal-first night inherited the flag). `reset_after_restart` logs an inherited flag.

### Files touched
**Local**
- `routers/producer.py`: shot fields, benched rows, `arm`/`spotlight` refusal, `map_live`/`prev_scene`/`rehearsal` in `state_doc`, `undo()`, `shot_refresh()`, `set_rehearsal()`, `set_fallback()`, `_take` re-assert + rehearsal, `_later`, `_rehearsal_on()`, `add_marker(note, kind='manual')`, `_start_sitting_if_stale()`.
- `routers/obs/__init__.py`: `_showing_card`, `_dark_ids`/`_dark_since`/`_fallback_done`, scan condition + three-state rule, tick emit/invalidate/fallback, `map_is_live()`, `_unfeature(by=)`.
- `integrations/obs_ws.py`: `prev_scene`, pre-request provisional tag, 'obs' attribution, rename.
- `integrations/relay_producer.py`: TTLs, `_dispatch` for seven commands, `_shot_keys` skip.
- `web/app/views/ttrpg/producer/{template.js,console.js}`, `web/css/views/producer.css`.
- `docs/PORT_CONTRACTS.md`, remote-console spec TTL line, README hotkeys (drop "Space auto"), new spec doc.

**Remote**
- `routers/producer.py`: `COMMANDS` += seven; `TTL_DEFAULT_S` undo/shot_refresh = 5.
- `portal/producer.js`: label map (fallback 'automatic'), CUT/UNDO, Shift+Enter/Z/L, dim/badges/guard, ⋯ menu, on-air, rehearsal/fallback controls, `paintShots` filters `benched`, `paintMarkers` defaults `kind`.
- `portal/style.css`, `tests/test_producer.py`.
- **Portal and local ship together** — an un-updated portal renders benched tiles as armable.

### Contracts

| cmd | args | TTL s |
|---|---|---|
| `undo` | `{}` | 5 |
| `shot_refresh` | `{key}` | 5 |
| `card` | `{character_id, show_card}` | 30 |
| `on_stream` | `{character_id, on_stream}` | 30 |
| `reorder` | `{character_id, delta: ±1}` | 30 |
| `rehearsal` | `{on}` | 30 |
| `fallback` | `{seconds}` | 30 |
| `take` (existing) | `{transition:'Cut'}` | 5 |

| key | meaning |
|---|---|
| `producer_rehearsal:s<session_id>` | '1'/'0'; reset by the stale-sitting helper |
| `producer_fallback_s` | global; seconds, '0' = off |
| `producer_markers:s<session_id>` | existing; rows gain `kind` (readers default 'manual') |

| wrapper | obs-websocket request |
|---|---|
| none new | all traffic via existing `refresh_browser_source`, `set_preview_scene`, `trigger_transition`, `set_transition`, `switch_scene` |

- **Hotkeys**: Shift+Enter CUT; Z Undo; L LOCK. No collisions — F, C, R, N, U, T, G stay reserved; never Space/F-keys/Ctrl+digit.

### Tests
- `tests/test_obs_ws_studio.py` → `prev_scene` on switch/event/rename; provisional tag survives an inline-dispatched event; in-OBS change tags 'obs'.
- `tests/test_obs_auto_return.py`, `test_obs_spotlight.py` → bare `_unfeature()` stays 'broadcast'; timer path is 'return'.
- `tests/test_obs_auto_cam.py` → three-state rule incl. console-open + auto-cam-off clears `_auto_dark_ids`; 'feed' emit + invalidate; fallback with recorder on `obs_ws.switch_scene`, `producer_active` stubbed, `time.monotonic` patched, marker read via `producer._markers()`.
- `tests/test_obs_closeups.py` → `_showing_card` with real `_tile_url`/`_card_base`, no host stubs.
- `tests/test_producer_api.py` → shot fields; benched order after `SPECIALS_BACK` (update `test_state_document`); arm/spotlight refuse; `/undo`; Cut expects `('transition','Cut',None)` then re-assert; unsaved-fade case; Fade override via patched `p._later`; rehearsal; portal-first stale reset; `/shot/refresh`; `/fallback` rejects negatives.
- `tests/test_relay_producer.py` → dispatch of seven commands; `rp.ttl_for('undo', {})` == 5; `_shot_keys` omits benched.
- `../ScenePlayRemote/tests/test_producer.py` → each command stages; undo TTL 5.0; unknown 400.

### Acceptance (check on a live OBS)
1. Cover a lens, auto-cam OFF, console open: tile dims 'dark' on both consoles; digit + Enter warns, Enter again takes; uncover clears within ~2 s.
2. ⋯ → Card on: badge 'card' within a second, Broadcast page agrees; Bench moves the tile after the specials with no key; Return renumbers.
3. ⋯ → Refresh source: only that browser source reloads.
4. Fallback 5 s, closeup on Program, cover lens: party scene within ~7 s (first-vote stamp), tag 'CHANGED BY dark fallback', incident marker, Preview untouched.
5. In OBS Studio Mode, **double-click/Transition** a scene (a single click only moves Preview): tag 'CHANGED BY OBS'; Z within 10 s restores with the saved fade. Scene link → 'scene link'. Auto-return → 'auto-return' **only with a configured group wide shot**.
6. Fade 300 saved: Shift+Enter cuts instantly, next Enter fades. Repeat with **nothing saved** and OBS on Fade 300; then a 1000 ms override — no clipped fade.
7. Header: OFF AIR / ON AIR (recording only) / ENDING on post-show card.
8. L: keys and clicks toast locked, works with OBS disconnected; Kill/Rebuild confirm while ON AIR.
9. Rehearsal: Enter, Shift+Enter, Z all toast, Program never moves, log shows REHEARSAL; off the next night, including a portal-first night.
10. Portal mirrors everything; an undo staged while local is offline expires with a warn note.

### Risks and skeptic's corrections
- **`showing` predicate**: plan copied `_mapping_rows`' `startswith(_card_base())`, which flags every tile as 'card' today → use `_showing_card` in both places.
- **`_unfeature` tag**: changing it inside the function mislabels the DM's Group button → parameter, default 'broadcast'.
- **CUT re-assert**: comparing against `_saved_transition()` after the override always matches → capture before.
- **Benched `spotlight`**: reachable without arm and persists a featured id with no tile → refuse.
- **Auto-cam OFF with console open** froze cards → three-state rule.
- **Fallback latency** was overstated → first-vote stamp, honest tooltip.
- **Benched placement** clipped the post-show card on an old portal → after `SPECIALS_BACK` + portal filter.
- **Stale badges after repair** → `_invalidate_shots()` on all four paths.
- **Event-before-tag race** → provisional tag pre-request.
- **Portal-first rehearsal inheritance** → shared stale-sitting helper.
- **Inline `threading.Timer` patch recurses `_sweep`** → `_later` hook.
- **Fallback tests** need explicit stubs (obs_ws disabled under conftest; two `appsettingGet` stores).
- **Remaining risks**: extra 96×54 screenshot per camera every 2–5 s with auto-cam off (measure once on a Pi with 8 tiles); 'obs' heuristic can mis-tag a >5 s slow OBS confirm (cosmetic); fallback vs scene-link race is documented, not prevented; agree marker `kind` vocabulary (manual/take/incident/break/clip/cue) with Build 1 before landing.
- **Ordering**: pure-server fixes first (`_showing_card`, `_unfeature(by=)`, `prev_scene`), then scan split, shot fields, CUT/rehearsal/undo, fallback last on the server, then both UIs feature-by-feature, then remote commands and docs.
- **Windows**: nothing platform-specific; say so in the spec.

---

## Build 3 — Talk to the table
**Goal** — A one-line, acked cue channel between producer, DM and each player that never goes over the air, plus a per-talent tally (red ON AIR / green NEXT) on local pages, the LAN My Camera page, the portal header and the remote console. Local computes everything; remote caches, filters and stages; nothing new in OBS.
**Effort** — 5.5–6 days (skeptic-adjusted from 4): 1.5 cues local, 1 tally local (incl. shots-cache bypass and `link_ready` plumbing), 1.5 remote + portal (4.9k-line `app.js`), 1 tests (18 across two suites), 0.5–1 live acceptance + Windows run. The test/acceptance line is what the planner under-budgeted.

### What it does (per item)

#### Cue store + local endpoints (`routers/producer.py`)
- **`add_cue(sender, to, text, character_id=None)`** appends `{id, at, from, to, character_id, name, username, text, ack_at}` to setting `producer_cues:s<id>` (ring of 50, `_sfx()` idiom as `producer_markers`, under a `_cues_lock`).
- **Sanitising**: strip `[\x00-\x1f]`, cap at 200 chars (not `set_profile`'s 60); empty text → 400.
- **Player target** must be a `kind=='player'` entry of `shots()` (else 400 `bad_target`); username comes from `db.session.get(tblCharacters, id).user.username`, since shot rows carry no user.
- **One ack signature**: `ack_cue(cue_id, *, username=None)` — `None` = DM/producer, string must match the row; idempotent, returns not-found for ids rolled out of the ring (never raises).
- **Endpoints**: `POST /ttrpg/producer/api/cue` (DM only; `role='player'` → 403), `POST .../cue/{id}/ack` (player only own rows), `GET .../cues` (player sees only `to=='player'` with own username, one filter).
- **Emits** `events.emit('cue', ...)` plus `_emit_state()`; `state_doc()` gains `cues` (tail 20) so the remote console rides the existing `producer_state` push.
- **Privacy**: player cues emit text on the parameterised `character:<id>` topic; the pinned `cue` topic carries only `{kind, id, to, username}` for player targets.

#### Console UI (`template.js`, `console.js`, `producer.css`)
- **`#pc-talkback-slot`**: `<select id="pc-cue-to">` (DM first, then player shots), rebuilt on shots-signature change but **preserving the selection**.
- **Chips**: DM → Wrap in 5 / Going to break / Stand by / Back in 1; player → You're muted / Fix camera / Look at the lens / Closer to the mic.
- **Free line** `#pc-cue-text` (maxlength 200), Enter sends; chip goes amber on send, green with check when `ack_at` lands in `state.cues`.
- **Inbox**: `to=='producer'` rows newest first, unacked highlighted with Got it.
- **Hotkeys** Q / Shift+Q handled before the `state.connected` gate (like K, V); `#pc-cue-text` needs its own keydown for Esc/Enter because the document handler returns early for INPUT targets.
- Hint line: `Q cue · Shift+Q got it`.

#### DM + player delivery on local pages (`layouts/ttrpg.js`)
- **`#sp-cue-banner`** (amber sibling of `#relay-health-banner`) subscribes to `cue`; fallback GET every 15 s, guarded by `store.get('user')` being set (401 → `auth.expired()`).
- **Suppressed on `/ttrpg/producer`** — every producer is a DM login, so without this the console would banner its own cues. The console inbox owns them there.
- **Solo-DM rule** (written into the spec): `to:'dm'` cues show only in the console inbox when the sender is the only DM login; Shift+Q and banner Got it stamp the same row.
- **DM reply chips**: Break after this scene / Cut to map / Wrap up / Stand by + free line → `{from:'dm', to:'producer'}`.
- **Player**: only own-username `to=='player'` cues, no chips; `toast.info` 5 s, banner until acked.

#### Tally computation + pinned `tally` topic
- **`tally_doc()`**: from `obs_ws.current_state()` + shots → `{connected, studio_mode, program, preview, on_air:{cid:'program'|'preview'|'off'}, names, party_program}`.
- **Rules**: Program == party → every shot `program` (+ `PRODUCER_TILE_ID` when `producer_on_screen()`); closeup → that member; Preview counts only while `studio_mode`; map/show cards → nobody.
- **Cache bypass**: call `_build_shots(set(built))` directly, or `_invalidate_shots()` on `kind in {on-stream, build, feature, group}` — otherwise benching never re-evaluates (2 s cache keyed only on scene list).
- **Change detector**: `events.add_listener(_tally_listener)`; one locked, daemon `threading.Timer(0.1)`, body under `db.session_scope()`, swallows exceptions, JSON-compares `_tally_last`, emits only on change. Never on the caller's thread.
- **`connected` flag** distinguishes OBS down from nobody on air (obs_ws blanks the cache on disconnect).
- **Also folded into `state_doc()`** so producer_state heartbeats carry it for remote consoles.
- `GET /ttrpg/producer/api/tally` for first paint; `tally`/`cue` in `events.TOPICS` + `topics.js`, not in `_MEDIA_TOPICS`.

#### Tally on local pages (`layouts/ttrpg.js`, `obs_my_feed.js`)
- **Navbar pill `#sp-tally`**: DM sees `ON AIR Carl, Jankis · NEXT Map`; player sees red/green dot for own characters (ids from `/api/v1/characters?scope=mine`).
- **`redraw()` re-paints** from cached state or the pill vanishes on every store change.
- **My Camera page** maps route id `dm` → `obs.DM_TILE_ID` (-1).
- Tooltip explains Preview needs an open console holding Studio Mode.

#### Relay plumbing (`relay_producer.py`, `relay_ws.py`, `relay_receiver.py`)
- **`rp.link_ready()`** called from `_session_loop` right after `_set_state('connected')` (inside session_scope) — `link_up()` runs before `connected`, so its sends would silently drop; `_push_loop` idles with no remote console.
- **`link_ready` snapshot**: one `tally` frame + one `cues` frame `{username: cue|null}` that **replaces** the hub cache (fixes acks lost during an outage staying pending forever).
- **`_on_event`**: `tally`/`cue` fire-and-forget, wrapped in try/except (`WsUnavailable` can race the `connected()` check; listeners must not raise).
- **`_dispatch`**: `cue` → `add_cue('producer', ...)`; `cue_ack` → `ack_cue(id)`.
- **Receiver**: handle `cue_ack` in `apply_relay_mutations` *before* `_apply_mutation`, match `cue.username == char.user.username`, append to applied ids, `continue` — never touch `changed_chars` (avoids a full sheet push per Got it).

#### Remote + portal
- **Remote**: `COMMANDS` + `TTL_DEFAULT_S` gain `cue`/`cue_ack`; `gm_ws` mtypes `tally`, `cue`, `cues`; hub `set_tally`/`set_cues`/purge; `stream.py` `event_visible(event, is_producer, username)` filters player cues by username and seeds tally + pending cue after `session_state`.
- **Portal**: `#header-player` pill (visible on every tab; camera card is on Settings), map-tab cue banner, Producer-tab slot mirroring console chips via `cmd('cue')`/`cmd('cue_ack')`; expired `producer_ack` → red "not delivered"; `rejected: unknown command` → "local ScenePlay too old".
- **Player ack**: `mutate('cue_ack', {cue_id}, as_player=cue.name)` → `POST /api/v1/character/mutate` with field `data` (not `mutation_data`); frame carries `mutation_data` as a JSON string and `player_name` = character name.

### Files touched
- **Local** `routers/producer.py`: cue store, `ack_cue`, `tally_doc`, listener, three endpoints, `state_doc` additions.
- `core/events.py`, `web/app/topics.js`: `tally`, `cue`.
- `integrations/relay_producer.py`, `relay_ws.py`, `relay_receiver.py`: `link_ready`, sends, dispatch, receiver branch.
- `web/app/views/ttrpg/producer/{template,console,index}.js`, `web/css/views/producer.css`: talkback slot.
- `web/app/layouts/ttrpg.js`, `web/app/views/ttrpg/obs_my_feed.js`: banner, pill, dot.
- `tests/test_producer_api.py`, `test_relay_producer.py`, `test_relay_receiver.py`.
- `docs/PORT_CONTRACTS.md` (relay row **and** Live updates topic list), spec `2026-09-18-remote-producer-console-design.md` (Cues and tally section, compat statement, Windows: no path/os.name changes).
- **Remote** `routers/producer.py`, `producer_hub.py`, `routers/gm_ws.py`, `routers/stream.py`.
- `portal/app.js`, `portal/producer.js`, `portal/index.html`, `portal/style.css`.
- `tests/test_producer.py`.

### Contracts
| cmd | args | TTL s |
|---|---|---|
| `cue` | `to: 'dm'\|'player'`, `character_id` (required for player), `text` ≤200 | 60 |
| `cue_ack` | `id` (from `state.cues`) | 30 |

| key | meaning |
|---|---|
| `producer_cues:s<session_id>` | JSON ring of 50 cue rows; no cleanup endpoint in this build |

| wrapper | obs-websocket request |
|---|---|
| none | — |

- **Q** focuses cue line (last target); Enter sends, Esc leaves.
- **Shift+Q** acks newest unacked incoming cue.
- **Collision**: T (obvious "talk") is claimed by Duo shot, hence Q. Nothing else claims Q.

### Tests
- `tests/test_producer_api.py` → party scene puts every shot on air; closeup + studio preview rules; emits only on change; `/tally` open to `role='player'`; strip/cap/emit; player target on grid (real `tblUsers`+`tblCharacters` fixture); ack scoping via conftest `player` fixtures; `state_doc` cue tail.
- `tests/test_relay_producer.py` → `ttl_for` 60/30, dispatch, expiry; `rp._on_event` called directly (listener isn't registered under `SP_INTEGRATIONS=0`); `link_up` under `_state='connecting'` defers instead of dropping.
- `tests/test_relay_receiver.py` → `cue_ack` mutation acks by username, skips `changed_chars`.
- `tests/test_web_assets.py::test_topics_match_backend` → red until `topics.js` updated.
- `ScenePlayRemote/tests/test_producer.py` → command TTLs capped at 60; tally cached and streamed; visibility per username; stream seeds from `cues` snapshot; `/character/mutate` with `data` yields JSON-string `mutation_data`.

### Acceptance (check on a live OBS)
1. Console → DM "Wrap in 5": chip amber; DM dashboard (other browser) banners + toasts within 1 s; Got it → chip green.
2. DM "Cut to map" → console inbox highlighted; Shift+Q clears it.
3. 250-char line to a player → stored 200; that player's My Camera and my-character pages banner; another player sees nothing; **no banner on the console page itself**.
4. Portal: same player sees banner on Map tab ~1 s; Got it lights local chip; portal DM sends "Fix camera", ack returns; unplug 90 s → chip red "not delivered".
5. Tally: party scene → all red; closeup → one red; Preview arm → green; all consoles closed → no green, tooltip explains; **bench a player → grey within 2 s**; map → all grey.
6. Relay off: LAN works; socket down: no log exception; reconnect → portal pills correct after hello (`link_ready`).
7. Windows: Timer/session_scope path runs; `make check` + remote pytest green.

### Risks and skeptic's corrections
- **`link_up` fires before `connected`** — plan's guard silently dropped every hello push; use `link_ready()` after `_set_state('connected')`.
- **Shots cache hides benching** — 2 s cache keyed on scene list; bypass or invalidate on stream-kind events.
- **`/mutations` doesn't exist** — it's `/character/mutate` with `data`; `as_player` must be the cued character's name or a multi-character login acks the wrong sheet.
- **Shot rows carry no user** — fetch `tblCharacters.user.username`; single `ack_cue` signature.
- **Producer is a DM login** — layout banner must skip the console route; solo-DM rule made explicit.
- **Receiver pushes the whole sheet per ack** — handle before `_apply_mutation`, skip `changed_chars`.
- **Acks lost during outage** stayed pending on the hub — `cues` snapshot replaces the cache.
- **Role is `'player'`, not `'user'`** — use conftest fixtures.
- **Listener never registered in tests** — call `rp._on_event` directly.
- **Local `cue` topic leaks text** to every LAN user — route player text over `character:<id>`.
- **Tally recompute runs forever** on every OBS event even with no subscriber — acceptable, stated; gate on subscriber/`rw.connected()` if it hurts.
- **Portal pill keyed on `String(character_id)`** — stale character pushes leave it grey; a re-push fixes it.

---

## Build 4 — Run the clock

**Goal** — Give the director FTB / stand-by, a go-to-break / back pair, an end-of-show macro and a hard-out back-timer on both consoles, all executed on local. Remote stages one command per action; anything that moves Program or an output carries a 5 s TTL.

**Effort** — 5.5–6.5 days (skeptic's number, over the planner's 4–5). Dominated by FTB's lock / in-memory mirror / three reconcile paths (~1.5 d), break/back with the reordered Back (1.5 d), the portal mirror with hold-to-confirm and older-local guards (~1 d), and live-OBS verification of the Studio Mode swap plus the `_do_feature` / `api_group` decisions (0.5–1 d).

### What it does (per item)

#### FTB / stand-by (F, latching)
- **Engage:** `ftb()` in `routers/producer.py` — `obs_ws.ensure_scene(obs.black_scene_name())` (empty scene `'ScenePlay Black'`, override `obs_black_scene`), so silent by construction.
- **Globals muted:** `special_inputs()` → for each named input with `input_muted()` False, `set_input_mute(name, True)`; `ObsRejected 600` (already removed by `_mute_machine_mics`) is skipped, never fatal.
- **Return scene:** current Program; if Program is already black, return = `obs._cut_scene_name('party')`. Disengage falls back to party when return is empty or black.
- **Switch:** `switch_scene(black, transition=_saved_transition(), by='producer')`; Preview and `_armed` untouched.
- **Ordering under `_ftb_lock`:** clear the in-memory mirror and the key BEFORE the return switch, so the resulting `CurrentProgramSceneChanged` cannot schedule a second clear. Same lock serialises `ftb()` against `_take`'s clear.
- **Take while engaged:** `_take` calls `_ftb_clear(switch=False)` after `trigger_transition` — Program is the taken shot, globals come back.
- **State:** `ftb: {on, return, since_s}`; `on` = key set AND program == black. Console: FTB button lit, Program tag reads `FTB` + return name. Never list the black scene in `_scenes_in_obs` (pin with a test) — `_build_audio` would nest the party audio into it.

#### FTB gating and auto-disengage
- **In-memory mirror:** `_ftb = {'on', 'black'}` written by `ftb()` / `_ftb_clear()` / reconcile; the `events.add_listener` callback reads only this and hands off unconditionally to `threading.Timer(0, …)` held in `_ftb_timer`. No `_sfx()`, no DB on the OBS reader thread.
- **Timer bodies** run inside `with core.appctx.ctx.app_context():`.
- **Gates:** `_schedule_return._fire` skips its switch (not `_unfeature` — `api_group` is a human and must still cut); `obs_scene_for_sceneplay_scene()` returns `''` while `obs.ftb_engaged()`.
- **`_do_feature` decision:** skip its "Program on party" switch while engaged (keep layout/feature) so the battlemap's initiative buttons (`/ttrpg/obs/api/next`) do not silently unmute the mics. Record in the spec.
- **Human cuts end FTB:** `_cut`, `_do_switch`, view-player, `api_group`, a switch inside OBS.
- **Reconcile** in `open_console()`, `_on_obs_connected` and `reset_after_restart`: program == black keeps FTB, otherwise `_ftb_clear(switch=False)`.
- **Console close:** decide up front — FTB/break are on-air state and survive `_off_if_idle` (Broadcast page then needs an "FTB engaged" badge + release), or the last close disengages. A solo DM opening the battlemap hits this every time.

#### Break scene + Go to break (Shift+I)
- **Setting** `producer_break_scene:s<id>` via `POST /break-scene` from a `<select>` of `state.scenes`.
- **Snapshot first** (unsuffixed `producer_break`): `muted_ids`, `card_ids`, `scene_id`, `featured_id`, viewed character, `countdown`, `at`; drop `program`/`armed` unless used for a "return to what was on" option.
- **Order:** take intermission FIRST (arm, `ensure_show_scenes` retry once, `take({})`), THEN activate the break scene with the scene link suppressed for that call — otherwise `_activate_scene`'s 2.5–5 s unwind leaves the last shot on air and queues a panic `take` behind it on `_cmd_loop`.
- **Then:** `_apply_mutes(_ordered_party(), True)`, `set_countdown` (default 600 s), `add_marker('Break', kind='break')`, `_emit_state()`.
- **Solo DM:** offer "keep DM live" on both macros or label the break as silent.
- **Response contract:** any failed step → `{ok: false, error: '<first failed step>', steps, break_on: true}`; portal paints Back from `state.break.on`, not the ack.
- **Import** `activatescene` lazily inside the function so tests can monkeypatch it.

#### Back from break (Shift+P)
- **Reordered:** `arm('party')` → `activatescene(pre-break)` → restore mutes per character from the snapshot → restore cards + `refresh_tiles()` → clear countdown → `add_marker('Back')` → clear key. Mutes go after activation because `apply_scene_audio` rewrites `obs_muted_ids`.
- **Take stays manual.** Button title says re-activation restarts that scene's music and, with the scene link on, may move Program early.
- **400 `break_not_on`** without a snapshot.

#### End show (hold-to-confirm, no hotkey)
- **Sequence:** `arm('post')` + take, countdown = `tail_s` (clamp 0–600; skip `set_countdown` when 0 — it rejects `<= 0`), `producer_ending_until` (unsuffixed), marker `'End'` kind `'end'`.
- **`_end_show_finish`** on `_end_timer` inside app context: stop stream then record via `set_output_active` (each guarded, errors folded into the ack and `state.ending.errors`), mute everyone, `set_barge(False)` if on screen, write `producer_clock_end:s<id>`.
- **Mutes:** snapshot and restore at next `open_console` / new-night start, or the next session opens fully muted.
- **Clock freeze:** `clock_frozen`, `clock_elapsed_s = end - start`; `clock_reset` and new-night start clear it.
- **Cancel** stops the timer, clears countdown + key; Program stays on Post. `reset_after_restart` clears a stale ending key.
- **UI:** 1.5 s pointer-hold fill; reads `ENDING 0:27 · cancel` during the tail.

#### Hard-out back-timer
- **`set_hard_out`:** `{at: 'HH:MM'}` (table-box local time, tomorrow if past), `{minutes}`, `{clear}`; stored `producer_hard_out:s<id>`; response echoes the resolved timestamp.
- **State:** `hard_out_at`, `hard_out_left_s` (negative once past). Readout amber < 10 min, red < 2 min, blinking `-MM:SS` after. No automation, no marker. Label input "table time" on both consoles.

#### Hotkeys and markers
- **Break branches** use `e.code === 'KeyI' / 'KeyP'` + `e.shiftKey`, placed after the Shift+digit block and before the arm test; arm test gains `!e.shiftKey`.
- **Markers:** `_markers()` defaults `kind='manual'` on read; both `paintMarkers` tolerate missing kind. `STATE_MARKERS` / `MARKERS_MAX` unchanged.

### Files touched
- **Local**
  - `routers/producer.py`: `ftb`, `_ftb_clear`, `_ftb_lock`, `_ftb` mirror, listener, `go_to_break`, `back_from_break`, `set_break_scene`, `end_show`, `end_show_cancel`, `_end_show_finish`, `set_hard_out`, marker `kind`, state fields, clock freeze, reconcile in `open_console` / `_on_obs_connected` / `reset_after_restart`.
  - `routers/obs/__init__.py`: `black_scene_name`, `ftb_engaged`, gates in `_schedule_return._fire`, `obs_scene_for_sceneplay_scene`, `_do_feature`; link-suppress flag.
  - `integrations/obs_ws.py`: `special_inputs`, `input_muted`.
  - `integrations/relay_producer.py`: `_dispatch`, `TTL_DEFAULT_S`.
  - `web/app/views/ttrpg/producer/template.js`, `console.js`, `web/css/views/producer.css`.
  - `docs/superpowers/specs/2026-09-14-producer-console-core-design.md` (endpoints, ~line 106), `2026-09-18-remote-producer-console-design.md` (command table).
- **Remote**
  - `routers/producer.py`: `COMMANDS`, `TTL_DEFAULT_S`.
  - `portal/producer.js`: shell/paint/wire/onKey/label, hold-to-confirm, guards for `d.ftb && d.ftb.on`, `d.break`, `d.ending`, `d.hard_out_left_s == null`.
  - `portal/style.css`: `pc-ftb`, `pc-hold`, `pc-hardout`.
  - `tests/test_producer.py`.

### Contracts

| cmd | args | TTL s |
|---|---|---|
| `ftb` | `{}` toggle or `{on: bool}` | 5 |
| `break_go` | `{seconds?: int}` | 5 |
| `break_back` | `{}` | 5 |
| `end_show` | `{tail_s: int}` (0 = now) | 5 |
| `end_show_cancel` | `{}` | 30 |
| `hard_out` | `{at}` / `{minutes}` / `{clear}` | 30 |
| `break_scene` | `{scene_id: int \| ''}` | 30 |

| key | meaning |
|---|---|
| `producer_ftb` (unsuffixed) | `{return, globals, at}`; on-air state |
| `producer_break` (unsuffixed) | break snapshot |
| `producer_ending_until` (unsuffixed) | tail deadline |
| `producer_break_scene:s<id>` | ScenePlay scene to activate on break |
| `producer_clock_end:s<id>` | freezes `clock_elapsed_s` |
| `producer_hard_out:s<id>` | hard-out deadline |
| `obs_black_scene` | black scene name override |

| wrapper | obs-websocket request |
|---|---|
| `special_inputs()` | `GetSpecialInputs` |
| `input_muted(name)` | `GetInputMute` |

- **Hotkeys added:** `F` FTB; `Shift+I` break; `Shift+P` back. END SHOW and hard-out have none.
- **Collision resolved:** Shift+I / Shift+P previously armed intermission / pre by accident.

### Tests
- `tests/test_producer_api.py` → FTB engage/return (incl. program-already-black), take clears without switching, listener hands off with no DB/obs call on the emitting thread, black never a shot, 600 skipped, break go order + snapshot, snapshot survives failed take with `ok:false`, Back restores snapshot with real `activatescene` and stubbed `apply_scene_audio`, end-show inline/tail/cancel/output failure, clock end cleared, hard-out cases, break-scene roundtrip. `fresh` fixture cancels `_ftb_timer` / `_end_timer`; `switch_scene` stub sets `state['current_scene']`.
- `tests/test_obs_auto_return.py` → `_fire` skips switch while FTB; `api_group` still switches; `_do_feature` per decision.
- `tests/test_obs_ftb_gate.py` → scene link `''` while engaged; `_scenes_in_obs` excludes black.
- `tests/test_obs_ws.py` → wrapper frames.
- `tests/test_relay_producer.py` → dispatch, TTLs, expired `end_show` never runs.
- `ScenePlayRemote/tests/test_producer.py` → seven commands accepted, unknown 400s.

### Acceptance (check on a live OBS)
1. F: Program fades to empty black, only unmuted globals mute, Preview/armed unchanged; F again restores exactly those.
2. While black: linked ScenePlay scene activation, auto-return and a battlemap turn step leave Program black; Enter, a Broadcast cut, Group, or an OBS click ends FTB within a second.
3. Check whether "Swap Preview/Program" moved Preview; if so re-assert `set_preview_scene(armed)`.
4. Shift+I: intermission on air immediately, break scene music follows, all voices muted, 10:00 countdown, Break marker.
5. Change mutes during break; Shift+P: exact pre-break mutes/cards/spotlight back, party armed, Program unchanged until Enter.
6. Hold END SHOW 1.5 s with 30 s tail: at 0:00 stream stops then recording, clock freezes and stays frozen on reload; cancel leaves outputs running.
7. Hard-out 3 min: amber/red/blinking negative; same on portal.
8. Portal: all commands land within the heartbeat; local down 10 s → END SHOW acks `expired`.
9. Kill local mid-FTB and restart; restart OBS mid-FTB: both reconcile correctly.
10. Windows box: same run — no `os.name` branch needed, so do not skip it.

### Risks and skeptic's corrections
- **Gate location:** plan gated `_unfeature`, which `api_group` (a human) also calls; gate `_schedule_return._fire` instead.
- **Missed mover:** `_do_feature` switches to party on initiative steps; decide skip-while-FTB explicitly.
- **Back order:** restoring mutes before `activatescene` is overwritten by `apply_scene_audio`; activate first.
- **Reader thread:** listener must not touch settings/DB (`_sfx` → SQLAlchemy on the OBS pump thread); mirror + unconditional Timer.
- **Timer threads** without `app_context()` leak thread-keyed sessions and flake tests with `database is locked`.
- **Suffix:** FTB/break/ending keys become unreadable when the session changes; store unsuffixed like `obs_muted_ids`.
- **Break latency:** activating first delays the intermission card 2.5–5 s; take first with the link suppressed.
- **Ack contract:** portal said "Break done" on a refused take; return `ok:false` with steps.
- **Return == black** left no way back; fall back to party.
- **Timecodes** on break/end markers stay wrong until Build 1 lands — schedule it first.
- **Studio Mode swap** may move Preview after the FTB switch; verify live.

---

## Build 5 — Polish the picture and the sound

**Goal** — Four finishing tools on both consoles with no new OBS sources and no schema: per-camera reframe that survives every rebuild, server-side hot-mic / dead-air alarms with one-tap fixes, a BED/FULL music bed with auto-duck and lip-sync offsets, and a stored pre-flight report with fix buttons. Local stays the only authority; the portal stages TTL'd commands and paints the state document.

**Effort** — 8–9 days across both repos (skeptic-adjusted from 6–7). Dominated by the shared substrate: the meter-owner refcount, the `_meter_tick` worker, the `music_target_db()` refactor, the special-mic mute path, and the rotation placement helper. **Order** (skeptic): substrate → bed/duck/sync → alarms → pre-flight → reframe last, crop + mirror first, rotation deferred if the budget is fixed. Wire each remote command with its local endpoint, not as a final pass.

### What it does (per item)

#### Music bed, auto-duck, sync offset (built first)
- **BED/FULL toggle** — `POST /ttrpg/producer/api/music-bed {on}` persists `producer_music_bed:s<id>`; hotkey `U` on both consoles.
- **One target function** — `producer.music_target_db()` = BED or FULL, minus `obs_duck_db` while the gate is open. `_place_music`, `api_volume(target=music)` and the ducker all push it via `_push_music_volume`; `api_volume` still persists FULL only.
- **Ducker** — rides `_meter_tick`; opens at -35 dBFS, holds 1.5 s, one `set_input_volume` per transition, never persisted.
- **Meter refcount** — `obs_ws.meter_events_acquire/release(owner)` over an owner set; `set_meter_events(on)` stays as the `console` owner shorthand. Duck holds owner `duck` so it works with no console open.
- **Restart/reconnect** — `reset_after_restart` and `_on_obs_connected` re-acquire the duck owner and re-push the target; disconnect clears the gate; closing the last console with a gate open restores once before release.
- **Sync offset** — `POST /ttrpg/obs/api/sync-offset {character_id, ms}` (±500) persists `obs_sync_ms:<cid>`, pushes `set_input_sync_offset`; `_apply_tile_audio` re-asserts it on every build. Audio strip rows gain `sync_ms`.
- **Broadcast page** — `api_state` gains `music_bed`/`duck` flags so its fader does not look wrong.

#### Hot-mic and dead-air alarms
- **Sampler** — one daemon thread in `routers/producer.py`, 10 Hz, factored as pure `_meter_tick(now, levels, snap)`; never started when `SP_WORKERS=0`; parks on a `threading.Event` when no console is open and duck is off.
- **No ORM in the loop** — show-card names from `_shots_cache` (`kind=='special'`), session suffix cached at toggle time, raw `appsettingGet` only; the rule is "never on the obs_ws reader thread", not "never request()".
- **Voice set** — every on-stream shot's cam input plus `GetSpecialInputs` mics (refreshed once a minute) when `_dm_audio_on()` is false.
- **Fader-relative levels** — `levels()` caches post-fader peak; compare against `threshold + saved fader` (or cache `inputLevelsMul[ch][2]` and gate on `_muted_ids()`). Pin the choice in tests with a faded tile.
- **Hot mic** — Program is a show card and any voice input above -40 dBFS within 2 s. **Dead air** — Program is not a show card, voice and both music inputs silent for 20 s.
- **Fix buttons** — banner in `#pc-banner`: "HOT MIC: Carl — [Mute everyone]" uses `mute {all:'everyone'}` **plus** the new `mute {special:'mics', muted}` path, naming the inputs touched. Client-only 5-minute snooze per kind.
- **Emit** — `state_doc()['alarms']`; `_emit_state()` on transitions only. Alarms compare Program, never Preview.
- **Solo DM** — decide: console-only (say so) or surface on the Broadcast page via the `obs` topic.

#### Pre-flight checks
- **`producer.checks()`** — on demand, cached 5 s, rows `{key, level, text, fix}`; every probe failure degrades to `warn`.
- **Rows** — OBS connected (`obs_connect`), Studio Mode (report), shots built (`build_closeups`), feed stale/dark via fresh `_probe_camera_dark` (`refresh_feed`), DM audible (tile on and unmuted, or tile off and a special mic present and unmuted via `input_muted`), YouTube linked, recording (local-only fix until Build 1's `output`), disk from `obs_ws.stats()['availableDiskSpace']` (<10 GB warn, <2 GB fail), meters flowing, "N of M remote players seen in 90 s".
- **Storage** — `POST /ttrpg/producer/api/checks` stores `producer_checks:s<id>`; `state_doc()['checks']` carries it so both consoles show the same page. Portal shows "running…" on the ack.

#### Reframe per tile (crop / rotate / mirror)
- **Setting** — `obs_tile_xform:<cid>` JSON `{crop, rot, mirror}`, per character.
- **Crop** — symmetric, in source pixels of the input's render size from `_input_settings` (wide 0, medium 12.5%, tight 25% cap); recomputed at every `place_item`, never cached as pixels.
- **Cam only** — applied in `_sync_party_scene` and `build_closeups` only when `_tile_plan` overlay is not `None`; `tile-xform` refuses feed-less members (their CAM source is the stat card).
- **Placement helper** — `_placement(rect, xform) -> {pos, bounds}` swaps bounds and offsets position for 90/270/180, shared by `place_item` and `animate_items` (frames carry the xform). Ship crop + mirror first; rotation only once this helper lands.
- **Mirror** — negative `scaleX`; `scene_item_transform` read-back reports "mirror not supported" if OBS normalised it.
- **Endpoint** — `POST /ttrpg/obs/api/tile-xform` merges partials, re-places in every scene via `scene_items`, calls `_invalidate_shots()`, `_emit('xform')`. Pass `xform=` only when non-default so existing stubs stay byte-identical.
- **UI** — ⌗ control on player/DM tiles opening a popover; state `_build_shots` rows carry `xform`.

### Files touched
- **Local**
  - `integrations/obs_ws.py` — `place_item(xform=)`, `_placement`, meter owner refcount, `set_input_sync_offset`, `input_sync_offset`, `input_muted`, `special_inputs`, `stats`, `scene_item_transform`.
  - `routers/obs/__init__.py` — tile-xform, sync-offset, refresh-feed endpoints; `api_mute special`; `_place_music` pushes `music_target_db()`; `_apply_tile_audio` re-asserts sync; `api_state` bed/duck flags; xform prune for deleted characters.
  - `routers/producer.py` — `_meter_tick`/worker, bed/duck/checks endpoints, `checks()`, `music_target_db()`, state_doc keys, restart/reconnect re-assertion.
  - `integrations/relay_producer.py` — dispatch for eight commands, `build_closeups: 60` TTL, `sync_ms` rows.
  - `web/app/views/ttrpg/producer/{template,console}.js`, `web/css/views/producer.css` — banner, Pre-flight card, BED/DUCK, ⌗ popover, sync field, `U` legend.
  - `docs/PORT_CONTRACTS.md` (add existing producer paths too), producer spec command table.
- **Remote**
  - `routers/producer.py` — `COMMANDS` + `TTL_DEFAULT_S` entries.
  - `portal/producer.js` — label map (unknown-command toast text), banner, card, buttons, popover, `U` key; hide every control when its state key is absent.
  - `portal/style.css` (no `producer.css` exists) — `.pc-*` classes.
  - `tests/test_producer.py`.

### Contracts

| cmd | args | TTL s |
|---|---|---|
| `tile_xform` | `character_id, crop?, rot?, mirror?` | 30 |
| `sync_offset` | `character_id, ms` (±500) | 30 |
| `music_bed` | `on` | 30 |
| `duck` | `on` | 30 |
| `checks` | — | 30 |
| `refresh_feed` | `character_id` | 30 |
| `obs_connect` | — | 30 |
| `build_closeups` | — | 60 |
| `mute` (existing) | `all:'everyone'` / `special:'mics'` / `character_id:-1` | 30 |

| key | meaning |
|---|---|
| `obs_tile_xform:<cid>` | `{crop, rot, mirror}` per character |
| `obs_sync_ms:<cid>` | audio sync offset, ms |
| `obs_music_bed_db` | bed level (default -18) |
| `obs_duck_db` | duck depth (default -12) |
| `producer_music_bed:s<id>` | `'1'` while BED |
| `producer_duck:s<id>` | `'1'` while auto-duck on |
| `producer_checks:s<id>` | `{rows, at}` last report |

| wrapper | obs-websocket request |
|---|---|
| `place_item(..., xform=None)` | `SetSceneItemTransform` |
| `scene_item_transform` | `GetSceneItemTransform` |
| `set_input_sync_offset` / `input_sync_offset` | `Set/GetInputAudioSyncOffset` |
| `input_muted` | `GetInputMute` |
| `special_inputs` | `GetSpecialInputs` |
| `stats` | `GetStats` |
| `meter_events_acquire/release` | Reidentify (op 3) |

- **Hotkey** `U` — BED/FULL, both consoles, ignored in inputs and while OBS is disconnected. No collision; `F, Shift+Enter, Z, C, R, N, L, T, G` remain free.

### Tests
- `tests/test_obs_ws.py` → `place_item` default still zeroes crop/rotation; xform writes source-px crop, `scaleX=-1`; refcount on/off semantics; new wrappers send the named requests.
- `tests/test_obs_tile_xform.py` → defaults, partial merge, validation, 25% cap, cam-only (overlay `None` refused), re-place in both scenes, mirror read-back warning, `_invalidate_shots`, `_placement` geometry.
- `tests/test_producer_alarms.py` → `_meter_tick` with fake levels and monotonic: hot-mic on show card only, dead air suppressed by music, faded tile threshold, special mics only when tile audio off, emit on transitions only, no thread under `SP_WORKERS=0`.
- `tests/test_producer_duck.py` → bed persists and pushes `music_target_db()`; `_place_music`/`api_volume` push the target not FULL; one push per transition; restart/reconnect re-assert; sync-offset clamp/persist/re-assert.
- `tests/test_producer_checks.py` → each row and fix, probe failure degrades, disk thresholds, cache honoured, stored report equals `state_doc['checks']`.
- `tests/test_producer_api.py` (line-285 shot-row equality updated), `tests/test_obs_cut.py`, `tests/test_obs_layout.py` → `place_item` stubs accept `xform`.
- `tests/test_relay_producer.py`, `../ScenePlayRemote/tests/test_producer.py` → eight commands dispatched/accepted, `build_closeups` TTL 60.

### Acceptance (check on a live OBS)
1. Press `U`: fader drops to bed; Rebuild on the Broadcast page — it **stays** at bed; `U` again returns to saved FULL.
2. DUCK on, speak: one `SetInputVolume` drop, one restore after ~1.5 s; close every console — ducking continues; restart local — DUCK/BED state and meters come back.
3. Cut to Intermission, talk into the DM's global mic: HOT MIC within 2 s; Mute everyone silences that mic and the banner clears.
4. Party scene, music stopped, silent 20 s: DEAD AIR; a tile faded to -20 dB does not trip it while music plays at bed level.
5. Set +120 ms on a player; Advanced Audio shows it; Build again — still 120 ms.
6. Cover a camera, mute the DM, stop recording, Run pre-flight from the portal; both consoles show the same report; Refresh reloads one source; Unmute fixes the row; with OBS closed every row degrades to warn.
7. Set Tight + mirror on a player: party and closeup show it, Overlay untouched, spotlight ease keeps it, Build closeups keeps it; a feed-less player's ⌗ is refused.
8. Rotate 90°: tile stays inside its cell through a spotlight ease (only if rotation shipped).
9. Same walk on the Windows appliance; `make check` green in both repos.

### Risks and skeptic's corrections
- **Rotation swings out of the cell** — plan assumed `animate_items` preserved a reframe by omission; with `alignment: 5` a rotated item pivots off its top-left and needs swapped bounds. Fix: shared `_placement` helper; defer rotation.
- **Feed-less CAM is the stat card** — plan applied xform to any CAM item. Fix: only when overlay is not `None`.
- **Mute everyone misses the DM** — `_apply_mutes` only touches cam inputs. Fix: `special:'mics'` path.
- **Rebuild lifts the bed** — `_place_music` and `api_volume` pushed raw FULL. Fix: `music_target_db()` everywhere.
- **Thresholds were fader-relative** — cached peak is post-fader. Fix: add the saved fader or cache pre-fader `[ch][2]`.
- **Worker did ORM on a plain thread** — `_cut_scene_name`/`_sfx` leak a sqlite read transaction. Fix: `_shots_cache`, cached suffix, `appsettingGet` only.
- **Existing stubs break** — five `place_item` stubs lack `**kw`; shot-row equality fails. Fix: pass `xform` only when non-default and update the stubs.
- **Tests would wake a real thread** — gate on `SP_WORKERS=0`, pure `_meter_tick`; confirm the gate does not disable it on Windows where workers are threads.
- **Compatibility** — new portal hides controls when keys are absent; older local answers "unknown command" and the toast says so.
- **Backup** — `tblAppSettings` is merge-excluded: reframes and sync offsets survive Replace, not Merge; prune keys for deleted characters.
- **Dead air with no music** — tables that play no music hit DEAD AIR by construction; decide a per-session flag or longer threshold and say so in the tooltip.
- **Mirror under bounds**, meters-on cost with the duck owner, chatty tables holding the bed low, a DM on a virtual cable being invisible, and pre-flight screenshot cost (bounded by cache and TTL) remain as documented risks.

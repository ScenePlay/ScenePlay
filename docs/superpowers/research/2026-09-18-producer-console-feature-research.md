# Producer console: what a director and a camera operator still need

Date: 2026-09-18. Research pass: 6 lenses (mixer desks, streaming studios, camera ops, directors, actual-play crews, audience), 85 candidates, every one fit-checked against the code, then a completeness critic. Chat moderation has its own brief: `2026-09-18-chat-moderation-brief.md`.

**What the console already is:** Studio Mode arm/Take, shot row with tally + hotkeys, 2 fps snapshot multiview, audio strip (meters, mutes, faders), room music, ScenePlay scene tiles, map view, spotlight, auto-cam pause, session clock, countdown, markers → OBS chapters, presence, producer camera + barge-in. All mirrored on the portal via staged commands.

**How to read this:** section 1 is the shortlist. Effort S = hours, M = a day or two, L = a week, XL = more.

---

## 1. Build next

### Director

**Stream health pill + incident markers** — M
- Poll `GetStats`, `GetStreamStatus`, `GetRecordStatus` every 5 s from a worker beside `_sweep`. Only while a console is open and an output runs. Never on the reader thread.
- HEALTH pill beside STREAM / REC. Amber: > 0.5 % dropped frames (last minute) or congestion. Red: > 2 %, `outputReconnecting`, or disk < 30 min at current rate.
- Hover shows the numbers. Entering red writes an `incident` marker (no OBS chapter).
- Fixes a real bug on the way: `stream_timecode` / `record_timecode` are set once at `_prime` and never advance. Every marker feature below depends on live timecodes.
- Serve it like `/levels` (polled), fold a snapshot into `state.health` for the remote heartbeat.
- Merges five candidates: encoder health, ingest health, on-air certainty, transport health, health strip.

**Outputs + recording safety on the console** — M
- Start / Stop stream and record as hold-to-confirm buttons over the explicit `/ttrpg/obs/api/output/{kind}`. Never a toggle.
- REC pill goes amber "not recording" while streaming.
- PAUSE / RESUME / SPLIT via `PauseRecord` / `ResumeRecord` / `SplitRecordFile`. Gate SPLIT on OBS ws ≥ 5.5. Relay OBS's rejection text when pause is impossible.
- After StopRecord, show the file path from `RecordStateChanged.outputPath`.
- YouTube go-live shortcut only when `youtube_live.linked()`, refused while already streaming (`api_yt_golive` makes a new broadcast per call).
- **Prerequisite for every YouTube item in section 3:** persist `yt_broadcast_id:s<id>` at go-live. One line.
- Remote commands `output` / `record_*` get the 5 s TTL class like arm / take.

**FTB / stand-by, latching (F)** — M
- Fade Program to an empty `ScenePlay - Black` scene with the saved transition. Second press fades back to the scene it left (kept in memory + a settings key).
- Silent by construction: ScenePlay audio is scene-bound. Only OBS global inputs leak. Mute them for the duration, restore after.
- Preview stays armed (vMix does the same).
- Exclude the black scene from `shots()` and inventory pruning.
- Decide: gate auto-cam / auto-return while engaged, or document they can cut away.
- Replaces the "safety slate" candidate. Later: a `standby` mode of panel.html with show art.

**Break + end-of-show macros, sequenced on local** — M (needs outputs above)
- Go to break (Shift+I): activate the break ScenePlay scene first (its scene link would otherwise yank Program), arm + take intermission, snapshot muted ids + card overrides to `producer_break:s<id>`, mute every voice, start countdown, marker `break`.
- Back (Shift+P): restore that exact snapshot, re-activate the pre-break scene, arm party. Take stays manual.
- End show: take Post with tail countdown, stop stream, stop record, mute, leave grid, marker `end`, freeze clock (`producer_clock_end:s<id>`).
- One remote command each, applied atomically.

**Auto-switch flash + undo (Z)** — S
- When `CurrentProgramSceneChanged` was not the console's own Take: flash "CHANGED BY auto-cam / scene link / broadcast page" on the Program tag for 3 s, offer Undo for 10 s (arm previous + take).
- Needs `prev_scene` in the obs_ws cache and two attribution fixes: auto-return's `_unfeature` tags `by='broadcast'`; a switch made inside OBS has no tag.
- Cuts are logged as `take` markers.
- This is the "go back" key. Flip-flop is skipped (see section 4).

### Camera operator

**Feed health on every tile + repair menu + take guard** — M
- Add to each shot: `feed` (live / ready / stale / nofeed), `dark` (`_auto_dark_ids`), `showing` (card / camera), `benched`. Emit when the dark set changes (the watcher only refreshes tiles today).
- Dark or stale tiles dim. Arming one warns; Enter needs a second press. Same when the map is armed and `map_state` says not live.
- Decouple the dark scan from `auto_cam_on()` or the badge goes blind when the producer pauses auto-cam.
- Per-tile menu: Refresh source (`refresh_browser_source` on that one input; warn it drops their mic for seconds), Card (`api_card_override`), Bench / Return (`api_on_stream`), Reorder behind a confirm (renumbers 1–9).
- Dark fallback setting `producer_fallback_s`: Program closeup subject dark for N s → cut to party + marker. Today a full-frame stat card sits on air until someone notices.
- Remote: three staged commands; badges come from state. Reference: StreamYard's People tab.

**Talent tally on the portal + DM pages** — M
- Local computes `on_air: {character_id: program | preview | off}` from the obs_ws cache, `_scene_map`, `featured_id`, party scene (everyone red when the party scene is Program).
- Relay: new fire-and-forget `tally` message. `gm_ws.py` publishes; `stream.py` already passes non-`producer_` events to players.
- Red / green dot on the player's camera card, a strip on the DM tab, local ttrpg layout subscribes to the same topic.
- Green exists only while a console holds Studio Mode. Say so in the tooltip.
- Shares the gm_ws branch with cues (below).

**Reframe per tile: crop / rotate / mirror** — M
- Wide / Medium / Tight symmetric crops, 90 / 180 / 270 rotation, mirror (negative scaleX) via `SetSceneItemTransform` on the person's cam item in the party scene and their closeup. Never the overlay item.
- Stored as `obs_tile_xform:<cid>`; re-applied by `_sync_party_scene`, `refresh_tiles`, `build_closeups` so reflows and Rebuild keep it.
- Crop applies before `OBS_BOUNDS_SCALE_INNER`, so the cell still fills.
- Cap Tight ≈ 25 %: a deep crop in a closeup is a 2x upscale.
- Works for LAN players who never open the portal.

### Both

**Text cues in both directions (talkback, step 1)** — M
- Chips + a free line in `#pc-talkback-slot`.
- Producer → DM: "Wrap in 5", "Going to break". Producer → player: "You're muted", "Fix camera". DM → producer: "Break after this scene", "Cut to map" (the direction the talkback phase never framed; most of a director's inbox).
- New pinned topic `cue` (not `producer`, which carries the whole state doc). Setting `producer_cue:s<id>`. Ack clears it and lights the chip. DM toast from `web/app/layouts/ttrpg.js`.
- Remote: new gm_ws mtype + a per-username filter in `stream.py` (today it knows only the `producer_` prefix).
- Cap and strip text as `set_profile` does.
- Later on the same path: discreet safety signal (player tap → HOLD banner → break macro), staged with the 60 s TTL so it never expires unseen.

**Markers grow up: kind, stream timecode, export, Clip** — S (export) / M (with Clip)
- Add `kind` (manual / take / incident / break / clip / cue) and `stream_timecode` to marker rows.
- "Copy chapters": YouTube block (forced `00:00`, ≥ 3 lines, 10 s spacing, collapsed markers merged) and a CSV, as text. Text is the only path on the remote, where downloads are inert.
- Clip (C): `StartReplayBuffer` / `SaveReplayBuffer`; take the path from `ReplayBufferSaved` (save is async). Start the buffer when either output starts, if OBS has one configured. Appends a `clip` marker.
- Depends on live timecodes from stream health.

---

## 2. Refinements of what exists or is planned

- **One hotkey table first.** Existing: 1–9, 0, B, P, I, O, Enter, V, M, K, Esc, Shift+digit. Proposed: F FTB · Shift+Enter CUT · Z undo · C clip · R arm roller · N / Shift+N turn · Shift+I / Shift+P break · Shift+B map inset · U music bed · L lock · T duo · G guides. Never Space (scrolls; push-to-talk lives on the remote camera card only), never F-keys, never Ctrl+digit.
- **CUT beside TAKE** — S. `take({'transition':'Cut','ms':0})` already works. `_take` must re-assert the saved transition afterwards or every non-producer switch hard-cuts until the next AUTO. Not the removed picker. Rate presets / stinger reopen the 2026-09-15 decision: your call, later.
- **On-air word + lock + rehearsal** — S. OFF AIR / ON AIR / ENDING in the header (REC counts). Client-only LOCK (L): ignores hotkeys, confirms Kill queue / Rebuild / Stop while on air. `producer_rehearsal:s<id>`: Take logs instead of transitioning.
- **Hot-mic + dead-air alarms** — S. From `obs_ws.levels()` over the whole Program: any unmuted voice while a show card is Program → banner with one-tap mute all; every voice < −50 dB for 20 s with no music → "dead air". Cheaper than per-feed audio-follow-video, same incident.
- **Music bed BED / FULL (U) + auto-duck** — M. Server loop over the meter cache calling `set_input_volume` on transitions only (`api_volume` persists on every call); refcount the meter subscription. Per-feed `SetInputAudioSyncOffset` persisted. Not a compressor sidechain: the DM tile is muted by default, it would duck on nothing.
- **Mixer presets** — M. Beside MUTE ALL BUT DM, per campaign. Keep the M button (critic overruled demoting it).
- **Duo shot (T)** — M. Modelled on `build_closeups`: two half-width rects in one re-pointed scene. **Map inset on closeups (Shift+B)** — M: `ensure_item` + `place_item` of the shared map source. These replace "layout presets".
- **Turn strip N / Shift+N** — S. Through the spotlight path, not `api_next` (cuts Program back to party). **Roll pop** — M: `ingest_relay_rolls` emits nothing on `dice`, so portal crits are invisible today (one-line fix); R arms the roller, Take stays manual.
- **Multiview** — S. Program-large layout in localStorage; `?w=` on `/snap` for one sharper enlarged tile; local-only `OpenVideoMixProjector` button. **Guides (G)** — S: thirds + safe boxes drawn from a `layout` block in the state doc.
- **Pre-flight `checks()`** — M. Server-side: connected, Studio Mode, shots built, feeds live / dark (fresh probe), DM unmuted, YouTube linked, recording on, disk. Both consoles, with fix buttons. "Who is in the room" is unknowable; report portal presence.
- **Second console.** Carry `by: {user, console}` on every state change and marker (the command row's username is dropped at execute today). Name consoles in the pill. Desk ownership as a courtesy (greyed buttons, "Take the desk"): local HTTP calls carry no console id.
- **Solo DM** — M. Collapsible desk strip on the ttrpg layout (Program name + thumbnail, TAKE, Party / Map / DM, mute-all-but-DM, marker). Console session must survive SPA navigation: leaving the route drops Studio Mode after 10 s today.
- **Tablet** — S. Wake lock, compact layout under 600 px with hold-to-Take, touch-sized faders.
- **Live-content phase.** Put `countdown_left_s` into `panel_state` for the intermission mode now. Panel on / off must go through the dice reflow, not `set_item_enabled`. Banner deck and reveal scene are the right shapes; the reveal picker is battlemap backgrounds, show art and PDF pages (there is no image library).
- **Rundown phase.** Segment timers with over / under; hard-out back-timer (`producer_hard_out:s<id>`, S, ships alone). Define a cue as "memory + content + note" so desk memories are its atom, not a parallel system.
- **Control surface** — M. Token-gated `GET /hot/{key}` for Stream Deck / Companion. Must count as console presence or Studio Mode never comes up.

---

## 3. Later / needs infrastructure

- **Everything YouTube-side**: ingest health (`liveStreams.list` healthStatus), viewer count, latency preset + honest CC pill (auto captions cannot be requested by API), embedded "as the viewer sees it" monitor (the only way to hear OBS's Program mix), chat with moderation + pin-to-panel. Unblocked by persisting `yt_broadcast_id` and a poller thread. Chat needs `liveChatMessages.streamList`: `list` at the suggested interval burns the 10,000-unit daily quota in a four-hour show.
- **Remote camera control via VDO.Ninja** (zoom, focus, exposure, forceKeyframe, per-feed stats): needs `&remote` / `&api` on push links with per-guest keys, the guest page holding the api.vdo.ninja socket, action list verified. iOS exposes no zoom / focus. Reframe (section 1) is the fallback that always works.
- **Real-time Program return** (OBS virtual camera + headless Chromium publisher into the room): needs a box with spare encode, v4l2loopback on Linux, a supervisor. Only worth it for a remote producer on a non-YouTube platform.
- **Multitrack recording** via `SetInputAudioTracks`: Advanced output mode + RecTracks mask + a container that carries six tracks. Detect and warn; never flip the profile.
- **OBS process supervision** (Start / Restart on `ExitStarted`, `--startstreaming`): needs `obs_is_local`, a known OBS path, `core/procutil` branches per platform.
- **Program loudness vs −14 LUFS**: the input-meter estimate is not K-weighted. Wait for the Loudness Dock plugin to expose numbers.
- **Desk ownership as a real lock**: presence contract widened to `{console_id, username}` in both repos.

---

## 4. Skip (and why)

- **Active-speaker spotlight** — `animate_items` at 700 ms per move turns crosstalk into a permanently moving grid; overwrites the turn feature.
- **Map+PIP / filmstrip party layouts** — nesting the map into the party scene changes Build, the dark probe and the closeups' audio carry.
- **DSK Names / Dice keyer** — the overlay source is the stat card for dark players; disabling it airs a half-black tile.
- **Flip-flop Preview after Take** — OBS's own swap setting is unreadable over the socket, so this double-swaps. Undo covers it.
- **Peek (hold Space)** — Preview is the armed shot; peek clobbers the arm and races the remote.
- **Exposure / focus hints from 320 px stills** — noisy, and the fix popover has nothing to drive.
- **Per-feed stats on the remote camera card** — measures the producer's own P2P leg, not what OBS receives.
- **Tally dot inside `tile.html`** — a poll in every OBS browser source to duplicate the console's border.
- **Demoting MUTE ALL BUT DM to a preset**; F-key, Shift+F, Ctrl+digit or Space hotkeys.
- **Shot sheet with notes** — revisit after bench / card / framing columns exist.

---

## 5. Summary table

| Feature | Role | Effort | Depends on | Phase |
|---|---|---|---|---|
| Stream health + incident markers | director | M | — | new |
| Outputs, recording safety, go-live shortcut | director | M | — | new (persists yt_broadcast_id) |
| FTB / stand-by | director | M | — | new |
| Break + end-of-show macros | director | M | outputs | rundown precursor |
| Auto-switch flash + undo | director | S | — | new |
| Feed health, repair menu, take guard, dark fallback | camera | M | — | new |
| Talent tally (portal + DM) | camera | M | gm_ws branch shared with cues | talkback |
| Reframe: crop / rotate / mirror | camera | M | — | new |
| Text cues, both directions | both | M | — | talkback, step 1 |
| Markers: kind, timecode, export, Clip | both | S / M | stream health | new; end-of-show |
| CUT beside TAKE | director | S | — | refinement |
| On-air word, lock, rehearsal flag | director | S | — | refinement |
| Hot-mic / dead-air alarms | audio | S | — | refinement |
| Music bed + auto-duck + sync offset | audio | M | — | refinement |
| Mixer presets | audio | M | — | refinement |
| Duo shot; map inset on closeups | director | M + M | — | new |
| Turn strip; roll pop | director | S; M | dice emit fix | new |
| Multiview layout, `?w=`, projector; guides | director | S | — | refinement |
| Pre-flight `checks()` | director | M | feed health | refinement |
| Attribution + courtesy desk | both | S | — | remote console refinement |
| Solo DM desk strip; session survives navigation | director | M | — | new |
| Tablet layout, wake lock | both | S | — | refinement |
| Hard-out back-timer | director | S | — | rundown |
| Rundown segment timers, over / under | director | L | hard-out | rundown |
| Countdown on intermission panel | graphics | S | — | live content (early) |
| Banner deck; reveal scene | graphics | M; L | overlay source | live content |
| Control-surface endpoint | both | M | — | new |
| YouTube: ingest health, viewers, latency / CC pill, confidence monitor | audience | S–M each | yt_broadcast_id | later |
| Chat, moderation, pin | audience | L | streamList, overlay | later (own brief) |
| VDO.Ninja camera control, keyframe, stats | camera | L | &remote / &api keys | later |
| Virtual-cam return feed | both | L | encode box, v4l2loopback | later |
| Multitrack recording | audio | M | Advanced output mode | later |
| OBS process supervision | director | M | obs_is_local, procutil | later |
| Program loudness | audio | M | Loudness Dock | later |
| Desk ownership lock | director | M | presence contract | later |

---

## 6. Suggested order

1. **Stream health** (fixes timecodes; everything else leans on it) → **outputs + recording safety** → **markers export + Clip**.
2. **Feed health + repair menu + take guard** → **auto-switch flash + undo** → **CUT, on-air word, lock**.
3. **Text cues both ways** → **talent tally** (same relay branch).
4. **FTB** → **break / end-of-show macros** → **hard-out timer**.
5. **Reframe**, **hot-mic / dead-air**, **music bed**, **pre-flight**.
6. Then the planned phases (live content, rundown) with the refinements above folded in.

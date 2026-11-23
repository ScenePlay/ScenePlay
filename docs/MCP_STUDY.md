# MCP for ScenePlay — feasibility study

*2026-11-23 · status: **built** the same day — ScenePlay `/mcp` (Utilities → AI Control) and the 3dObject voice characters as clients. The study below is kept as written.*

## TL;DR

- **Verdict: yes — good fit, low risk.** Music is already driven by small, plain Python functions
  (`sql.py`, `extensions.py`, `media/smart_scenes.py`). An MCP tool is a thin wrapper around each one.
- **Recommended shape:** an MCP server **inside the existing app**, mounted at `/mcp`
  (Streamable HTTP), **off by default**, **DM-only bearer token**.
- **No schema change, no Alembic revision, no remote (`../ScenePlayRemote`) change.**
- **Dependency:** `mcp` 2.3.0 — dry-run install on the Python 3.14 `.venv` resolves cleanly.
- **Size:** small spike (read tools + volume) → medium for the full music set with tests and a Settings toggle.

---

## What it would feel like

You type to Claude (or any MCP client):

| You say | Tools Claude calls |
|---|---|
| "What's playing? Turn it down to 30." | `now_playing` → `set_volume(30)` |
| "Skip this, it's too upbeat." | `skip` |
| "Play the Tavern playlist, but don't change the lights." | `list_playlists` → `queue_playlist(id, replace=true)` |
| "Make a playlist of 80s synth tracks for the chase scene." | `library_facets` → `preview_smart_playlist(rule)` → `create_smart_playlist(...)` |
| "Add those three dungeon songs to Boss Fight and put them first." | `search_library` → `add_to_playlist` → `reorder_playlist` |
| "Pause for 5 minutes, we're on a break." | `pause` (Claude can't time it — see Limits) |

---

## How music works today (what MCP would wrap)

| Concept | Where it lives | Function to call |
|---|---|---|
| **Playlist** = a scene | `tblScenes` + `tblMusicScene` (`orderBy`, `volume`, `loops` per song) | `CRUD_tblScenes`, musicScene add/del rows |
| **Smart playlist** | `tblSceneRules` (JSON rule) | `smart_scenes.match / create_scene / set_rule / refresh` |
| **Queue** | `tblMusic.que = 1` flag, played in active-scene `orderBy`, else random | `update_play_queue_selected`, `queue_scene_songs` |
| **Play a scene (full)** | music + video + LEDs + OBS scene + OBS audio | `routers.public._activate_scene` (under `_activate_lock`) |
| **Skip** | fade + mpv `stop` | `queue_next()` |
| **Pause / resume** | mpv `cycle pause` (toggle only) | `mpv_command('music', 'cycle pause')` |
| **Seek** | mpv `seek N` | `mpv_command('music', 'seek N')` |
| **Stop all** | clears queue, fades, kills video | `queue_kill()` |
| **Volume** | system sink: PulseAudio (Linux) / Core Audio (Windows) | `setvolume`, `currentvolume` |
| **Keep music playing** | appsetting toggle | `appsettingSetKeepMusicPlaying` |
| **Now playing** | `currentsong` / `CurrentScene` appsettings | `get_now_playing()` |
| **Library search / facets** | `tblMusic` + `tblMediaMetadata` | `/api/music` search, `smart_scenes.facet_options` |
| **Add from YouTube** | download queue | `addMediaToYT_que(url, name, 'mp3', scene_id)` |

---

## Proposed tool set

### v1 — music core

| Tool | Kind | Notes |
|---|---|---|
| `now_playing` | read | song, scene, volume, keep-music, queue count/duration |
| `search_library(text, genre, artist, decade, limit)` | read | default 25, max 100 rows — keeps replies small |
| `library_facets` | read | genres / artists / decades / kinds for building rules |
| `list_playlists(campaign_id?)` | read | name, id, song count, play time, smart or not |
| `get_playlist(id)` | read | songs in order, with per-song volume/loops |
| `set_volume(0–100)` / `get_volume` | write | clamp 0–100 |
| `skip` · `pause` · `resume` · `seek(seconds)` | write | pause/resume must be **idempotent** (see gotchas) |
| `stop_all` | write, destructive | `queue_kill()` — clears the queue |
| `queue_playlist(id, replace)` | write | **music only** — no lights/OBS |
| `play_scene(id)` | write | **full** scene activation (lights + OBS + music + video) |
| `queue_songs(song_ids, replace)` | write | ad-hoc queue |
| `create_playlist(name, song_ids, campaign_id?)` | write | plain scene + link rows |
| `add_to_playlist` · `remove_from_playlist` · `reorder_playlist` | write | |
| `preview_smart_playlist(rule)` · `create_smart_playlist(name, rule)` | read / write | reuses `smart_scenes` exactly |
| `set_keep_music(on)` | write | |

### Later phases

- `download_song(url, playlist_id)` — touches disk + network; opt-in.
- Video, LED patterns, WLED, lights off.
- OBS / producer console (Studio Mode preview/program).
- MCP **resources** (`sceneplay://nowplaying`, `sceneplay://playlists`) and **prompts** ("build a soundtrack for tonight's session").

### Left out on purpose

- `delete_playlist` — not in v1. If added: `destructiveHint`, and a required `confirm: true`.
- Anything users / auth / backup / network / settings.

---

## Architecture options

| | A. In-process `/mcp` (**recommended**) | B. Separate stdio bridge | C. Auto-expose routes (`fastapi-mcp`) |
|---|---|---|---|
| What | `MCPServer` mounted on the FastAPI app | small script that calls the HTTP API with a token | wraps every existing endpoint as a tool |
| Pros | calls real functions; one process; nothing extra to run | zero risk to the appliance; works with stdio-only clients | almost no code |
| Cons | must wire the SDK's lifespan into `app.py` | duplicates endpoint knowledge; many endpoints return text/plain | 300+ legacy routes, bad names (`/musicaddrow`), exposes too much, floods the model's context |
| Verdict | **build this** | optional ~50-line add-on later | **reject** |

### A — how it would plug in

- New module **`integrations/mcp_server.py`**: builds the `MCPServer`, registers tools.
- Tool bodies live in a plain module, e.g. **`media/music_tools.py`** — no MCP imports.
  → The built-in AI (`routers/ai.py`, Gemini) could reuse the same tool layer later.
- `app.py`: `app.mount('/mcp', mcp.streamable_http_app())` **before** the SPA catch-all.
- Lifespan: run `mcp.session_manager.run()` inside the existing lifespan (the SDK raises
  "Task group is not initialized" otherwise).
- Boot-crash guarded like the other integrations: if `mcp` is not installed or fails, log once and skip.
- Each mutating tool calls `events.emit('queue' | 'scene' …)` so open SPA tabs update live.

### Checked in the mcp 2.3 wheel

- `FastMCP` is **renamed `MCPServer`** (`from mcp.server.mcpserver import MCPServer`) — v1 tutorials won't paste in.
- **Sync tools run on a worker thread** (`anyio.to_thread.run_sync`) → `_activate_scene`'s 2.5 s sleep and
  `queue_kill`'s callers won't block the event loop.
- Tool `annotations` (`readOnlyHint`, `destructiveHint`) supported.
- `TransportSecuritySettings(allowed_hosts=…)` exists → DNS-rebinding protection.
- Dry-run adds: `cryptography`, `jsonschema`, `rpds-py`, `opentelemetry-api`, `httpx2`, `truststore`, …
  **Still to verify:** Pi (aarch64) wheels and `.venv-win`.

---

## Clients — what can actually reach a Pi on the LAN

| Client | Works? | How |
|---|---|---|
| **Claude Code** (PC on same LAN) | yes | `claude mcp add --transport http sceneplay http://<pi>:8086/mcp --header "Authorization: Bearer <token>"` |
| **Claude Desktop** | yes, via local bridge | stdio entry running a bridge (option B or `mcp-remote`) pointed at the Pi — *confirm current Desktop options in the spike* |
| **claude.ai web / mobile connectors** | not without exposing the Pi | connectors are called from the cloud; **do not** port-forward the appliance |
| **Local LLM apps** (LM Studio, Open WebUI, etc.) | yes | most support Streamable HTTP MCP; fully offline option |

- **Do not route MCP through the Render remote.** Local is the authority; remote stays a player portal.

---

## Local AI via Ollama (no cloud)

### Tested 2026-11-23 on the dev PC (RTX 5070 8 GB, Ollama 0.40.2)

4 fake tools (`set_volume`, `skip`, `list_playlists`, `queue_playlist`), Ollama `/api/chat`, `think: false`.

| Model | "Down to 30 and skip" | "Play boss fight, replace queue" | Verdict |
|---|---|---|---|
| `gemma4:12b` | `set_volume(30)` → `skip` ✅ | `list_playlists` → `queue_playlist(7)` ✅ | **good** |
| `qwen3.5:9b` | `set_volume(30)` → `skip` ✅ | `list_playlists` → `queue_playlist(7)` ✅ | **good** |
| `qwen3:8b` | `set_volume(30)` → `skip` ✅ | `queue_playlist(2)` ❌ **guessed an id** | avoid |

- Speed: first call 11–16 s (model loads into VRAM), then **~1–2 s**.
- Lesson: **tools take playlist names, not just ids**, and an unknown id returns the real list
  instead of failing silently.

### Two ways to wire it

| | 1. Built-in assistant (**recommended**) | 2. Generic MCP client |
|---|---|---|
| What | ScenePlay endpoint runs the Ollama tool loop itself | an off-the-shelf Ollama + MCP chat app connects to `/mcp` |
| Calls | `media/music_tools.py` directly — no MCP hop | the MCP server |
| UI | chat box in the SPA player bar | the other app's window |
| Needs MCP built first? | no | yes |

**Option 1 sketch**

- `integrations/ollama.py` — `chat(messages, tools)` against `ollama_url` (stdlib/`requests`, no new dependency).
- `POST /api/v1/assistant` (DM-only): user text → Ollama → run tool calls → loop (max ~5 rounds) → reply.
- Tool schemas generated from the same `music_tools` functions the MCP server registers → **one tool list, two doors**.
- Settings (appsetting rows, like `text_provider`): `ollama_url` (default `http://127.0.0.1:11434`), `ollama_model`.
- Every tool emits its SSE event, so the player bar updates as the AI acts.

### Voice: a 3dObject character runs the music

`../3dObject` already has rigged characters you talk to (VR or desktop): Whisper speech-to-text on the GPU →
Ollama → Piper voice from the character's mouth, with lip sync. Personas live in
`models/server-side/<model>.persona.json`.

**Why it's easy:** the voice pipeline (OllamaWeb `run_turn`) only consumes a **stream of reply text**.
Tool calling can live entirely inside `3dObject/voice/viewer_voice/llm.py`:

1. Send the chat to Ollama **with tools**.
2. If it returns tool calls → call ScenePlay → add the results → ask again.
3. Stream the final spoken reply as today ("Done — turned it down to thirty.").

OllamaWeb and `run_turn` stay untouched.

| Step | ScenePlay change? | How the character reaches ScenePlay |
|---|---|---|
| **1 — prove it** | none | ScenePlay's existing LAN-open URLs: `/api/nowplaying`, `/set_volume`, `/nextsong`, `/music_stopstart`, `/activatescenes/?id=` |
| **2 — proper** | `/mcp` built | voice service becomes an **MCP client**; tools appear automatically, same set Claude and the built-in assistant use |

**Must-haves**

- **Per persona, opt-in:** a "Controls ScenePlay" tick + ScenePlay URL. The barkeep runs the jukebox; others just talk.
- **Off on share links.** Share-link visitors (second port) can open `voice/ws` → `server.js` must mark those
  sessions and the voice service must drop the tools, or any guest can change your music.
- **Model needs `tools`:** `qwen3.5:9b` ✅ `gemma4:12b` ✅ — the roleplay models (`peach-9b`, `stheno-8b`) ❌ completion only.
- **VRAM:** `qwen3.5:9b` (6.4 GB) + Whisper (0.5 GB) fits in 8 GB; `gemma4:12b` + Whisper likely doesn't.
- **Only reversible tools by voice:** volume, skip, pause/resume, queue a playlist. No stop-all / delete — a
  mis-hearing must never wipe the queue.
- **Latency:** a tool round adds ~1–2 s before the first word (the 2 s target was for plain chat). Only personas with
  the tick pay it.

**Watch out:** room speakers playing ScenePlay music aren't cancelled by the browser's echo cancellation (it only
removes the page's own sound) → songs with vocals can trigger Whisper. Headset mic helps; **auto-duck** (ScenePlay
volume down while the character is hearing/speaking, back up after) fixes it and is a nice touch anyway.

### Where Ollama runs

| ScenePlay on | Ollama on | Notes |
|---|---|---|
| this PC | this PC | works today |
| Pi | gaming PC on the LAN | set `OLLAMA_HOST=0.0.0.0` on the PC; **Ollama has no auth** → LAN only, never port-forward |
| Pi | Pi | small models only, slow — not recommended |

---

## Security

- **Off by default.** Enabled by an appsetting row (existing `tblAppSettings`, no new column) or `SP_MCP=1`.
- **Always auth, even when the DM gate is off.** The old playback URLs are LAN-open, but MCP adds
  playlist writes — so it needs a token regardless.
- **Token:** dedicated, long-lived, stored as `instance/mcp_token` (like `jwt_secret`).
  - Generated / regenerated from Settings, shown once.
  - Compared with `hmac.compare_digest`; never logged, never in a URL.
  - Alternative: a normal DM login JWT (30-day TTL) — simpler but expires and dies on password change.
- `allowed_hosts` set to the box's own names/IPs (DNS-rebinding).
- Result limits on every list tool (max 100).
- Dev instance (`make dev`): `SP_INTEGRATIONS=0` → MCP off, so it can never drive the live players.

---

## Gotchas found

| Gotcha | Fix |
|---|---|
| Pause is `cycle pause` — a **toggle**. "Pause" twice = playing again. | Read mpv's `pause` property over IPC first; `pause`/`resume` set it explicitly. |
| `_activate_scene` also changes **LEDs, OBS scene, OBS audio, video**. | Two tools: `play_scene` (full) vs `queue_playlist` (music only). |
| `setvolume` sets **every PulseAudio sink**, not just mpv. | Name it "system volume" in the tool description; per-song volume stays on playlist links. |
| `queue_kill` honours **keep-music-playing**. | Report that in the tool result so the model isn't confused when music continues. |
| Queue is a **set + order**, not a list — no "insert after current song". | Order comes from the active playlist's `orderBy`; describe that in the tool text. |
| Only songs with `dnLoadStatus = 3` (downloaded) can queue. | Return "skipped N not yet downloaded". |
| Scene activations are serialized by `_activate_lock`. | Reuse the lock — never call `_activate_scene` directly. |

---

## Fit with project rules

- ✅ No new columns / tables / Alembic revision.
- ✅ No remote change — remote consumes nothing new.
- ✅ Linux + Windows — pure Python; volume already has both branches.
- ✅ Backups unaffected (token in `instance/`, same as other secrets).
- ✅ SPA stays in sync through `events.emit`.
- ⚠️ New dependency in `requirements.txt` (pin `mcp~=2.3`) — needs a Pi + Windows install check.

---

## Plan

| Phase | Scope | Done when |
|---|---|---|
| **0 — spike** | mount `/mcp`, token check, `now_playing`, `list_playlists`, `set_volume`, `skip` | Claude Code on the PC changes volume on the Pi |
| **1 — music core** | full v1 tool table, idempotent pause, Settings toggle + token UI, `tests/test_mcp.py` (in-memory MCP client, player functions mocked), README section | `make check` green on both venvs |
| **2 — atmosphere** | YouTube download, video, LEDs, lights off | |
| **3 — extras** | resources, prompts, optional stdio bridge, reuse tool layer in the built-in AI | |

---

## Questions for Eric

1. **Which client first?** Claude Code on the PC, Claude Desktop, or a local LLM?
2. **Default "play a playlist"** — music only, or full scene (lights + OBS)?
3. **Allowed actions** — may the AI download from YouTube? Ever delete playlists?
4. **Token** — dedicated MCP token (recommended) or reuse DM login?

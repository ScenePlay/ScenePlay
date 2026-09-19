# Producer camera, live link and barge-in (design)

Date: 2026-09-18. Status: approved in conversation; built in the same piece of work in both repos.
Builds on the remote producer console (spec 2026-09-18-remote-producer-console-design.md).

## Why

The producer switches the show in real time, so they must hear the table and see the cameras
with talkback-grade latency, and they sometimes step into the show themselves (a rules note, a
segment). Both come from things the table already runs: the VDO.Ninja room and the party grid.

## Decisions taken

| Question | Decision |
|---|---|
| Live link | The producer joins the table's VDO.Ninja room from their own push page: every mic, every camera and the music feed, sub-second. Not OBS's composed Program (the 1 fps snapshot stays for that). |
| Presence on stream | A tile in the party grid, LAST position, only while "barged in". No closeup shot. |
| Identity | Settings, like the DM tile: `obs_producer_stream_id` (minted), `obs_producer_name` (default "Producer"), `obs_producer_on_screen` ('0'/'1'). Tile id `PRODUCER_TILE_ID = -2`. No schema change. |
| Audio | The room always carries the producer's open mic to the table (talkback for free; their card's mute is the way to stay quiet). The stream hears them only through their tile, i.e. only while barged in. They get the normal mute button and fader in the audio strip while on the grid. |
| Video for the producer | Their push link drops the room's voices-only flag (`&novideo`) so they receive faces; players keep it. |
| Out of scope | Adding rules text or graphics to the stream (the live-content phase); a live Program feed. |

## Local

- `routers/obs`: `_ProducerTile` (mirrors `_DmTile`), `producer_tile()`, `producer_on_screen()`,
  `_tile_for_id(cid)` used wherever the DM was special-cased for lookups. `_ordered_party()` appends
  the producer after everyone else when on screen (saved order is ignored for them). Scene prefix
  `Producer - `. Card/tile leaves `producer` with the same token gate as `dm`.
- `models.ttrpg._vdo_url(kind, stream_id, producer=False)`: producer pushes skip `&novideo`.
- `routers/producer.py`: `POST /barge {on}` and `POST /profile {name}` (DM-gated) plus plain
  functions `set_barge(on)` / `set_profile(name)` for the relay. Barge re-lays the party scene
  (keeping the spotlight), refreshes tiles, invalidates shots, emits. The state document gains
  `producer: {tile_id, on_screen, name, push_url, feed}`.
- Console: a "Producer" block in the side card — name field, Barge in / Leave grid toggle, Camera
  link (opens the push page in a new tab; the local site is http on the LAN, so no embed).

## Remote

- Commands `barge {on}` and `producer_profile {name}`.
- Producer tab: the same block plus an embedded camera card (push page with `&cleanoutput`, start /
  mute / camera off / stop / open-in-tab), fed from `state.producer.push_url`. The link carries the
  room password like every player's own link; it reaches only producer-scoped sessions.

## Reflow rule (2026-09-19)
A reflow (barge, leave, spotlight, bench) never resizes a running browser source: OBS recreates the page on a
size change (reload + WebRTC renegotiation), which is what made barge-in stutter and cameras blank when the
member count crossed a grid boundary (3→4, 6→7, 9→10). Stale sizes are counted in the state document
(`stale_tiles`) and the console says so; only Build resizes, at the producer's chosen moment.

## Testing

Local: producer last in `_ordered_party` only when on screen; barge and profile endpoints; the tile
in audio rows and scene naming; push URL without `&novideo`; both relay commands. Remote: commands
accepted. Then a portal screenshot.

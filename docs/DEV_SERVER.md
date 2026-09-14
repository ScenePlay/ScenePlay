# Dev instance for testing (side-by-side with the live Flask box)

**Running now:** http://10.0.4.33:8086 (also http://127.0.0.1:8086 on this machine)

- Login (DM): username `yllonnoce`, password `x`
- Database: a COPY of the real ScenePlay.db (`<scratchpad>/live/real.db`) — nothing you do here touches the live box.
- Workers, relay/OBS integrations and cron are OFF in this instance (`SP_WORKERS=0 SP_INTEGRATIONS=0 SP_CRON_APPLY=0`), so scene activation
  records the queue but does not play media.

## What is ported
Everything: login/setup/recover, home + all media tables, utilities + library pages, backup/restore, the whole TTRPG
toolkit (characters, sheets, sessions, users, battle maps, 3D, textures, AI generation, monsters, reference
libraries, handouts), relay pages, the OBS Broadcast page, camera feeds and the OBS overlay sources, LED / WLED /
cron / server tables. See docs/SPA_PARITY.md for the per-page list.

## Restart
```bash
cd /mnt/Transfer/5FD1E1415AC80F29/dev/ScenePlay
for p in $(pgrep -f "[w]s.py --no-w"); do kill $p; done
SP_PORT=8086 SP_WORKERS=0 SP_INTEGRATIONS=0 SP_CRON_APPLY=0 \
SP_DB_PATH=<scratchpad>/live/real.db SP_MPV_SOCKET_PREFIX=/tmp/mpvsocket-dev- \
nohup .venv/bin/python ws.py --no-workers > <scratchpad>/live/server.log 2>&1 &
```
(`make dev` runs the same thing against the tree's own `ScenePlay.db`.)

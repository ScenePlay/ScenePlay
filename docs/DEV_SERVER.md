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

## This PC as the appliance (deployed working tree)

`scripts/deploy_local.sh` makes this checkout the box's ScenePlay: `~/ScenePlay` is a
symlink to it, `ScenePlay.db` in the tree is the real database, the app starts on login
via `~/Desktop/ScenePlay.sh` → `startApp.sh`, and nginx proxies port 80 to it.

Only one instance can own port 8086, so before pressing F5 stop the deployed one:

```bash
pkill -f 'ScenePlay/[w]s.py'      # the bracket keeps the shell from matching itself
```

F5 does this for you: `.vscode/tasks.json` stops the deployed copy before launch and
starts it again when the debug session ends (`preLaunchTask` / `postDebugTask`).
By hand, start it again with `~/ScenePlay/startApp.sh` (or just log in again).
Both F5 configs use the real `ScenePlay.db`; the "UI only" one never starts players,
integrations or cron, so it is safe to run against it.

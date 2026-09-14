# Cutting a box over from ScenePlay 1.x (Flask) to 2.x (FastAPI + SPA)

Same database file, same `instance/` secrets, same uploads, same watchdog, same port 8086.
Rollback is a directory swap for as long as no new Alembic revision has been applied (2.0.x adds none).

## Linux / Raspberry Pi
1. **Backup**: Utilities → Backup now; copy the zip off the box.
2. Stop 1.x: `systemctl --user stop sceneplay_watchdog.service`; `pkill -f "ScenePlay/ws.py"`; `pkill -f mpvsocket-`; check `ss -ltnp | grep 8086` is empty.
3. Checkpoint the WAL so the copy is complete: `sqlite3 ~/ScenePlay/ScenePlay.db "PRAGMA wal_checkpoint(TRUNCATE)"`.
4. `mv ~/ScenePlay ~/ScenePlay-flask` — this is the rollback copy; keep it for one release.
5. Put the 2.x tree at `~/ScenePlay` (a git checkout — the Utilities update card needs one); `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (`--break-system-packages` on Pi OS if pip insists).
6. Carry data over from `~/ScenePlay-flask`: `ScenePlay.db` (+ `-wal`/`-shm` if present), `instance/` (**`secret_key` is mandatory** — OBS browser-source tokens are HMACs of it; API keys live there too), `static/uploads/`, `static/thumbs/`, `backups/` (or symlink the upload folders).
7. nginx (`supportFiles/default.txt`): the `/api/v1/events` location needs `proxy_buffering off; proxy_read_timeout 3600s; proxy_set_header Connection '';` — reload nginx.
8. Start the watchdog again (`systemctl --user start sceneplay_watchdog.service`). Check `curl localhost:8086/isAlive` shows the new pid and `curl localhost:8086/api/server-info` reports version 2.x.
9. Cron: unchanged unless the install directory moved (then regenerate from the Cron Schedules wizard).
10. OBS: unchanged if `instance/secret_key` was carried; otherwise Broadcast → **Reload sources** once.
11. Everyone logs in once (JWT replaces the Flask session cookie); tokens then renew themselves for 30 days.
12. Browser extensions: unchanged.

## Windows
Same order with `.venv-win`, `install.bat` and `startApp.bat`; the scheduled task keeps pointing at `startApp.bat`.

## Rollback
- Before any new Alembic revision (all of 2.0.x): stop the watchdog, `mv ~/ScenePlay ~/ScenePlay-2`, `mv ~/ScenePlay-flask ~/ScenePlay`, copy `ScenePlay.db` back (the 2.x app only added the `tblEvents` table, which 1.x ignores), start the watchdog.
- After a new revision: restore the pre-cut-over backup zip from step 1 through the 1.x Utilities page.

## Side-by-side testing before the cut-over
`make dev` (or the command in `docs/DEV_SERVER.md`) runs 2.x on 8086 with workers, integrations and cron OFF against a DB copy (2.x replaces 1.x on a box — they never run side by side on the same machine). `make parity FLASK=http://<1.x box>:8086 NEW=http://127.0.0.1:8086` diffs the safe GET endpoints between the two.

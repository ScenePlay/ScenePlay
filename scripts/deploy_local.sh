#!/bin/bash
# Make THIS working tree the ScenePlay appliance on this Linux box
# (docs/CUTOVER.md, adapted to a desktop where the tree lives on a shared
# drive). Idempotent — safe to re-run. Steps:
#   1. stop any running instance (+ its mpv players)
#   2. promote dev.db to ScenePlay.db (first run only)
#   3. ~/ScenePlay -> this tree (an old Flask install is kept as ~/ScenePlay-flask)
#   4. start-on-login entry (~/.config/autostart -> ~/Desktop/ScenePlay.sh)
#   5. nginx: add the SSE block from supportFiles/default.txt (needs sudo; skipped if refused)
#   6. start the app via startApp.sh and check /isAlive + /api/server-info
set -euo pipefail
W="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$W"

echo "== 1. stopping any running instance"
pkill -TERM -f 'ScenePlay/[w]s.py' 2>/dev/null || true
for _ in $(seq 1 20); do ss -ltn 2>/dev/null | grep -q ':8086 ' || break; sleep 0.5; done
pkill -f 'mpvsocket-' 2>/dev/null || true
if ss -ltn 2>/dev/null | grep -q ':8086 '; then echo "port 8086 still busy — stop it by hand"; exit 1; fi

echo "== 2. database"
if [ -f ScenePlay.db ]; then
  echo "ScenePlay.db already in place"
elif [ -f dev.db ]; then
  sqlite3 dev.db "PRAGMA wal_checkpoint(TRUNCATE)" >/dev/null
  mv dev.db ScenePlay.db; rm -f dev.db-wal dev.db-shm
  echo "dev.db promoted to ScenePlay.db"
else
  echo "no database here — ws.py will create an empty ScenePlay.db"
fi

echo "== 3. ~/ScenePlay -> $W"
if [ -L "$HOME/ScenePlay" ]; then
  ln -sfn "$W" "$HOME/ScenePlay"
elif [ -d "$HOME/ScenePlay" ]; then
  [ -e "$HOME/ScenePlay-flask" ] && { echo "~/ScenePlay-flask already exists — move it aside first"; exit 1; }
  mv "$HOME/ScenePlay" "$HOME/ScenePlay-flask"
  echo "old install kept as ~/ScenePlay-flask (rollback copy)"
  ln -s "$W" "$HOME/ScenePlay"
else
  ln -s "$W" "$HOME/ScenePlay"
fi
ls -ld "$HOME/ScenePlay"

echo "== 4. start on login"
mkdir -p "$HOME/.config/autostart"
cp -p supportFiles/ScenePlay.sh "$HOME/Desktop/ScenePlay.sh"
sed "s|Exec=/something.sh|Exec=$HOME/Desktop/ScenePlay.sh|" supportFiles/sceneplay.desktop.txt \
  > "$HOME/.config/autostart/sceneplay.desktop"
echo "installed ~/.config/autostart/sceneplay.desktop"

echo "== 5. nginx SSE block"
if [ -f /etc/nginx/sites-available/default ] && ! grep -q 'api/v1/events' /etc/nginx/sites-available/default; then
  if sudo cp supportFiles/default.txt /etc/nginx/sites-available/default && sudo nginx -t && sudo systemctl reload nginx; then
    echo "nginx updated and reloaded"
  else
    echo "nginx NOT updated (sudo refused or config test failed) — run later: sudo cp supportFiles/default.txt /etc/nginx/sites-available/default && sudo nginx -t && sudo systemctl reload nginx"
  fi
else
  echo "nginx already has the SSE block (or no nginx site)"
fi

echo "== 6. starting"
nohup "$HOME/ScenePlay/startApp.sh" >> "$W/sceneplay_launch.log" 2>&1 &
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8086/isAlive >/dev/null 2>&1 && break; sleep 1; done
echo "isAlive:     $(curl -s http://127.0.0.1:8086/isAlive)"
echo "server-info: $(curl -s http://127.0.0.1:8086/api/server-info | head -c 200)"
echo "log: $W/sceneplay_launch.log"

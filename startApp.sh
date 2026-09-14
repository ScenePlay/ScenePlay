#!/bin/bash
# Run from the project root so worker-relative paths and ScenePlay.db resolve.
cd ~/ScenePlay
# Two venv layouts: `.venv` (git checkout on a shared drive, README "Linux venv")
# or the Pi installer's, where ~/ScenePlay itself is the venv (bin/activate).
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
elif [ -f bin/activate ]; then
  source bin/activate
fi
python3 ~/ScenePlay/ws.py
deactivate 2>/dev/null

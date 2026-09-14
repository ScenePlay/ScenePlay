"""The Grid.js table editors (13 ScenePlay tables). Each module exposes a
`router`; this package aggregates them so app.py includes one router."""
import importlib

from fastapi import APIRouter, Depends

from security.deps import sceneplay_dm_gate

router = APIRouter(dependencies=[Depends(sceneplay_dm_gate)])
open_router = APIRouter()

for _name in ('campaigns', 'music_scene', 'video_scene', 'music_media', 'video_media',
              'genre', 'dn_load_status', 'server_role', 'scene_pattern', 'wled_pattern',
              'led_config', 'server_ip', 'cron_schedule'):
    try:
        _mod = importlib.import_module(f'routers.tables.{_name}')
    except ModuleNotFoundError as exc:
        if exc.name == f'routers.tables.{_name}':
            continue
        raise
    if getattr(_mod, 'router', None) is not None:
        router.include_router(_mod.router)
    if getattr(_mod, 'open_router', None) is not None:
        open_router.include_router(_mod.open_router)

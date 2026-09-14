"""GET /api/v1/events — the one SSE stream per browser tab."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

import core.events as events
from security.deps import ApiError, get_current_user, sceneplay_locked_for

router = APIRouter()

_MEDIA_TOPICS = {'nowplaying', 'queue', 'downloads', 'scene', 'update', 'netscan'}
_PING_S = 30


@router.get('/api/v1/events')
async def stream(request: Request, topics: str = '', last_id: int = 0,
                 user=Depends(get_current_user)):
    wanted = {t.strip() for t in topics.split(',') if t.strip()} or {'server'}
    bad = [t for t in wanted if not events.topic_ok(t)]
    if bad:
        raise ApiError(400, f'unknown topics: {", ".join(bad)}')
    if user is None:
        raise ApiError(401, 'login required', code='login_required')
    if wanted & _MEDIA_TOPICS and sceneplay_locked_for(user):
        raise ApiError(403, 'This server restricts ScenePlay to DM logins.', code='sceneplay_locked')
    hub = events.hub()
    if hub is None:
        raise ApiError(503, 'event hub not running')

    last = request.headers.get('last-event-id')
    try:
        last = int(last) if last else int(last_id or 0)
    except ValueError:
        last = 0

    sub = hub.subscribe(wanted)

    async def gen():
        try:
            snaps = {t: hub.snapshot(t) for t in wanted if hub.snapshot(t) is not None}
            from version import __version__
            snaps['server'] = {'version': __version__}
            yield {'event': 'hello', 'data': json.dumps(snaps, default=str)}
            if last:
                for rid, topic, data in await asyncio.to_thread(hub.replay_since, last, wanted):
                    yield {'id': str(rid), 'event': topic, 'data': json.dumps(data, default=str)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    rid, topic, data = await asyncio.wait_for(sub.queue.get(), timeout=_PING_S)
                except asyncio.TimeoutError:
                    yield {'event': 'ping', 'data': '{}'}
                    continue
                frame = {'event': topic, 'data': json.dumps(data, default=str)}
                if rid:
                    frame['id'] = str(rid)
                yield frame
        finally:
            hub.unsubscribe(sub)

    return EventSourceResponse(gen(), ping=_PING_S)

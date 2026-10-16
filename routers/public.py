"""Session-less endpoints (ported from routes/main.py). Called by cron curl
jobs, the browser extensions, other ScenePlay boxes, the forked players, the
watchdog and the TTRPG pages — paths preserved verbatim, no auth, no gate."""
import json
import os
import platform
import threading
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from extensions import *          # noqa: F401,F403
from sql import *                 # noqa: F401,F403
from core.procutil import pid_alive, uptime_info
from sql import appsettingFlagGet
from models.mediaMetadata import tblmediametadata
from lighting.ledPlayer import *           # noqa: F401,F403
from integrations.remotes import *             # noqa: F401,F403
import integrations.relay_broadcaster as relay_broadcaster
from wLed.wledCommand import *    # noqa: F401,F403
import lighting.led_patterns as led_patterns
import core.config as config
import core.events as events
from routers._util import json_body
from security.deps import ApiError

router = APIRouter()


def getWledPatternBySceneID(sceneID):
    from models.wledPattern import tblwledpattern as tbl
    return tbl.query.filter(tbl.scene_ID == sceneID).all()


@router.get('/favicon.ico')
def favicon():
    return FileResponse(os.path.join(config.STATIC_DIR, 'favicon.ico'),
                        media_type='image/vnd.microsoft.icon')


@router.post('/set_volume')
def set_volume(body: dict = Depends(json_body)):
    new_volume = int(body['volume'])
    setvolume(new_volume)
    return Response('Volume set successfully!', media_type='text/plain')


@router.get('/api/songandvideocount')
def songandvideocount():
    data = select_data_stats()
    dataDict = []
    for item in data:
        # songQCnt/videoQCnt keep their historic slot; QDur adds the queued
        # seconds so the pill bar can show total remaining time.
        dataDict.append({item[0]: item[1], item[0].replace('QCnt', 'QDur'): item[2]})
    return dataDict


def queue_counts():
    """Flat form of songandvideocount for the SSE `queue` topic."""
    out = {}
    for d in songandvideocount():
        out.update(d)
    try:
        out['scene_states'] = scene_queue_states()
    except Exception:
        pass
    return out


@router.get('/api/mediameta/{media_type}/{media_id}')
def mediameta(media_type: str, media_id: int):
    """Full extracted metadata for one media row — feeds the table info modal."""
    if media_type not in ('music', 'video'):
        raise ApiError(400, 'media_type must be music or video')
    m = tblmediametadata.query.filter_by(media_type=media_type, media_id=media_id).first()
    if not m:
        return JSONResponse(None)
    d = m.to_dict()
    from media.thumbs import store as thumb_store
    d['thumbnail'] = thumb_store.url(media_type, media_id) or d.get('thumbnail')
    return d


@router.get('/api/server-info')
def server_info():
    """Fingerprint endpoint used for LAN discovery — an answering box IS a
    ScenePlay server. Intentionally unauthenticated and read-only."""
    import socket as _socket
    from version import __version__
    name = appsettingGet('server_name', None) or _socket.gethostname()
    try:
        from models.ledConfig import tblledconfig
        has_led = db.session.query(tblledconfig.ledConfig_ID).filter(
            tblledconfig.active == 1).first() is not None
    except Exception:
        has_led = False
    return {
        'app':          'ScenePlay',
        'server_name':  name,
        'version':      __version__,
        'os':           platform.platform(),
        'machine':      platform.machine(),
        'cores':        os.cpu_count() or 1,
        'capabilities': {
            'led':   has_led,
            'relay': appsettingGet('relay_enabled', '0') == '1',
        },
    }


def addMediaToYT_que(url, flname, mediaType, scene_ID):
    """Intake entry point (form + Chrome extension). A playlist URL is queued for
    background expansion; a single video is deduped by its YouTube id and shares
    one media row/file across scenes. `flname` is an OPTIONAL display-name override.
    NOTE: pass the RAW url here (do NOT pre-strip &list=) so playlists are detected."""
    from media.ytid import is_playlist_url
    media_type = 'music' if mediaType == 'mp3' else 'video'
    if is_playlist_url(url):
        return enqueue_playlist(url, media_type, scene_ID)
    return enqueue_single(url, mediaType, scene_ID, flname or '')


@router.post('/api/ChromeExtensionAddVideo')
def ChromeExtensionAddVideo(data: dict = Depends(json_body)):
    url = data['url']
    flname = (data.get('flname') or '').strip()
    mediaType = data['mediaType']
    scene_ID = data['scene_ID']
    addMediaToYT_que(url, flname, mediaType, scene_ID)
    events.emit('downloads', {'reason': 'enqueued'})
    return 'Success'


@router.post('/updateWLEDSupport')
def updateWLEDSupport(data: dict = Depends(json_body)):
    ServerIP_ID = None
    try:
        if 'ServerIP_ID' not in data:
            raise ApiError(400, 'ServerIP_ID required')
        ServerIP_ID = data['ServerIP_ID']
        addEffectsPallettes(ServerIP_ID)
    except ApiError:
        raise
    except Exception as e:
        print(e)
    return Response(f"'Update Effects and Pallettes using ServerIP_ID': {ServerIP_ID}",
                    media_type='text/plain')


# Serializes scene activations (see routes/main.py history: overlapping runs
# interleaved their play-flag writes and wedged playback).
_activate_lock = threading.Lock()


@router.api_route('/activatescenes/', methods=['GET', 'POST'])
def activatescene(id: str = None):
    with _activate_lock:
        _activate_scene(id)
    events.emit('scene', {'scene_id': id})
    return {'ok': True, 'scene_id': id}


def _players_alive():
    try:
        if config.PLAYER == 'ipc':
            # the persistent mpv is always alive — ask whether a track is loaded
            if int(appsettingFlagGet('currentsong') or 0) > 0:
                return True
        elif pid_alive(int(appsettingAudioPlayPID()[0][2])):
            return True
    except Exception:
        return True
    try:
        return pid_alive(int(appsettingVideoPlayPID()[0][2]))
    except Exception:
        return True


_UNWIND_SECONDS = 2.5


def _restart_players(scene_id):
    was_playing = _players_alive()
    queue_next()
    queueVideo_next()
    if was_playing:
        time.sleep(_UNWIND_SECONDS)
    selected = [row[2] for row in get_MusicSceneSongs_BYSceneID(scene_id)]
    if selected:
        update_play_queue_selected(selected)
    selectedVideo = [row[2] for row in get_VideoScene_BYSceneID(scene_id)]
    if selectedVideo:
        update_video_queue_selected(selectedVideo)
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)


def _activate_scene(id):
    try:
        scene_id = int(id)
    except (TypeError, ValueError):
        scene_id = None
    appsettingSet('remote_send_last_fail', '')
    appsettingSet('wled_send_last_fail', '')
    appsettingSet('relay_push_last_drop', '')
    if scene_id is not None and scene_id > 0 \
            and appsettingGetCurrentScene() == scene_id:
        # Re-click of the ACTIVE scene: bounce the players only — unless the
        # lights went dark in between (scene media ran out, or the Lights-off
        # button), in which case the strip no longer shows this scene and
        # must be pushed again.
        _restart_players(scene_id)
        if _lights_dark():
            _push_scene_lights(id)
        return
    if scene_id is not None:
        appsettingSetCurrentScene(scene_id)
    if scene_id is not None and scene_id > 0:
        try:
            from routers.obs import obs_scene_for_sceneplay_scene
            obs_scene = obs_scene_for_sceneplay_scene(scene_id)
            if obs_scene:
                import integrations.obs_ws as obs_ws
                if obs_ws.connected():
                    obs_ws.switch_scene(obs_scene, timeout=1.5)
        except Exception as exc:
            print(f'OBS scene link skipped: {exc}')
        try:
            from routers.obs import apply_scene_audio
            apply_scene_audio(scene_id)
        except Exception as exc:
            print(f'OBS scene audio skipped: {exc}')
    scnPat = CRUD_tblScenePattern([id], "bySceneID")
    ledPattern = led_patterns.build_payload((r[2], r[3], r[4]) for r in scnPat)
    if str(id) == '-1':
        rows, rowsVideo = [], []
    else:
        rows = get_MusicSceneSongs_BYSceneID(id)
        rowsVideo = get_VideoScene_BYSceneID(id)
    appsettingAudioPlayFlagUpdate(0)
    appsettingVideoPlayFlagUpdate(0)
    was_playing = _players_alive()
    queue_kill()
    try:
        if was_playing:
            time.sleep(_UNWIND_SECONDS)
        selected = [row[2] for row in rows]
        if selected:
            update_play_queue_selected(selected)
        selectedVideo = [row[2] for row in rowsVideo]
        if selectedVideo:
            update_video_queue_selected(selectedVideo)
        _push_scene_lights(id, ledPattern)
    finally:
        queue_next()
        appsettingAudioPlayFlagUpdate(1)
        appsettingVideoPlayFlagUpdate(1)


# tblAppSettings flag: '1' once lights_off() has darkened every output while a
# scene is still recorded as current. Lets a re-click of that scene know the
# strip no longer shows it (see _activate_scene). Cleared by every scene push.
_LIGHTS_DARK = 'lights_dark'


def _lights_dark():
    return (appsettingFlagGet(_LIGHTS_DARK) or '0') == '1'


def _push_scene_lights(id, ledPattern=None):
    """Push scene `id`'s lighting everywhere: WLED controllers (direct and via
    the relay) and the RPiLED payload (this box, Remote boxes, the relay)."""
    if ledPattern is None:
        scnPat = CRUD_tblScenePattern([id], "bySceneID")
        ledPattern = led_patterns.build_payload((r[2], r[3], r[4]) for r in scnPat)
    data = getWledPatternBySceneID(id)
    if data is not None:
        for row in data:
            setWledEffect(row.effect, row.pallette, row.color1, row.color2, row.color3,
                          row.speed, row.brightness, row.server_ID)
    if len(data) == 0:
        wled_Off()
    relay_broadcaster.broadcast_wled(data)
    dispatch_led(ledPattern)
    appsettingSet(_LIGHTS_DARK, '0')


def lights_off():
    dispatch_led(led_patterns.OFF_PAYLOAD)
    wled_Off()
    relay_broadcaster.broadcast_wled([])
    appsettingSet(_LIGHTS_DARK, '1')


@router.api_route('/api/lights-off', methods=['GET', 'POST'])
def lights_off_endpoint():
    """Session-less on purpose: called by the forked player workers the
    moment the current scene's media finishes."""
    lights_off()
    return {'message': 'lights off'}


_LED_CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Private-Network': 'true',
    'Access-Control-Max-Age': '86400',
}


@router.options('/receive_led_patterns')
def receive_led_patterns_preflight():
    return Response(status_code=204, headers=_LED_CORS)


@router.post('/receive_led_patterns')
def receive_led_patterns(body=Depends(json_body)):
    """Another ScenePlay box (Remote role) or a remote player's portal page
    pushing a lighting payload at THIS box's strip."""
    patterns = body.get('patterns') if isinstance(body, dict) else None
    if not isinstance(patterns, list):
        raise ApiError(400, 'expected {"patterns": [...]}')
    kept = [p for p in (led_patterns.normalize(x) for x in patterns) if p]
    if patterns and not kept:
        raise ApiError(400, 'no recognised pattern types')
    payload = json.dumps({'patterns': kept}) if kept else led_patterns.OFF_PAYLOAD
    if not is_raspberry_pi():
        return {'message': 'LED patterns received; this box has no Pi strip'}
    insert_LEDJSON(payload)
    threaderLED()
    return {'message': 'LED patterns received and applied'}


@router.get('/api/nowplaying')
def nowplaying():
    """Current song/video (human display names) + active scene."""
    return get_now_playing()


@router.api_route('/nextsong', methods=['GET', 'POST'])
def nextsong():
    appsettingAudioPlayFlagUpdate(1)
    queue_next()
    return Response("'message': 'next song'", media_type='text/plain')


@router.api_route('/nextvideo', methods=['GET', 'POST'])
def nextvideo():
    appsettingVideoPlayFlagUpdate(1)
    queueVideo_next()
    return Response("'message': 'next Video'", media_type='text/plain')


@router.api_route('/killqueue', methods=['GET', 'POST'])
def killqueue():
    queue_kill()
    time.sleep(5)
    events.emit('scene', {'scene_id': -1})
    return Response("'message': 'queue killed'", media_type='text/plain')


@router.get('/isAlive')
def isAlive():
    rowWatchManage = CRUD_tblAppSettings(['WatchManage'], "byName")
    watchManage = rowWatchManage[0][2] if rowWatchManage else 1
    return {'isAlive': 'true', 'pid': os.getpid(), 'WatchManage': watchManage,
            'uptime': uptime_info()}


from media.mpv_ipc import mpv_command as _mpv_command   # noqa: E402


@router.post('/video_seek')
def video_seek(body: dict = Depends(json_body)):
    _mpv_command('video', f"seek {body['value']}")
    return {'success': True}


@router.post('/video_stopstart')
def video_stopstart():
    _mpv_command('video', 'cycle pause')
    return {'success': True}


@router.post('/music_seek')
def music_seek(body: dict = Depends(json_body)):
    _mpv_command('music', f"seek {body['value']}")
    return {'success': True}


@router.post('/music_stopstart')
def music_stopstart():
    _mpv_command('music', 'cycle pause')
    return {'success': True}


# ── keep-music-playing toggles (open: cron + TTRPG pages) ─────────────────────

@router.post('/api/keepmusicplaying')
def toggle_keep_music():
    current = appsettingGetKeepMusicPlaying()
    appsettingSetKeepMusicPlaying(0 if current else 1)
    return {'keep_music': 0 if current else 1}


@router.get('/api/keepmusicplaying/off')
def set_keep_music_off():
    appsettingSetKeepMusicPlaying(0)
    return {'keep_music': 0}


@router.get('/api/keepmusicplaying/on')
def set_keep_music_on():
    appsettingSetKeepMusicPlaying(1)
    return {'keep_music': 1}


@router.get('/assets/media/video/{media_id}.{ext}')
def asset_media_video(media_id: int, ext: str):
    """Inline (range-capable) stream of a library video for battle maps and
    OBS cards. Open like static files: those pages have no session."""
    import media.shared_assets as shared_assets
    from extensions import database
    path, real_ext = shared_assets.library_video(database, media_id)
    if not path or real_ext != ext.lower() or ext.lower() not in shared_assets.VIDEO_EXTS:
        raise ApiError(404, 'not found')
    mime = {'mp4': 'video/mp4', 'webm': 'video/webm', 'ogv': 'video/ogg'}[ext.lower()]
    return FileResponse(path, media_type=mime)


# derived SSE topics fed by this module
events.register_derived('nowplaying', lambda: get_now_playing(), 1.0)
events.register_derived('queue', queue_counts, 1.0)


# ── SPA player bar bootstrap (media pages; gated like the control page) ──────
from security.deps import sceneplay_dm_gate   # noqa: E402


@router.get('/api/v1/player', dependencies=[Depends(sceneplay_dm_gate)])
def player_state():
    try:
        vol = currentvolume()
    except Exception:
        vol = 0
    try:
        keep = bool(appsettingGetKeepMusicPlaying())
    except Exception:
        keep = False
    return {'volume': vol, 'keep_music': keep, 'nowplaying': get_now_playing(),
            'counts': queue_counts()}

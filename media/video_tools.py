"""Video control for AI clients, the video half of media.music_tools ("play the campfire video", "skip the video",
"stop the video").

Same contracts as the player bar and /nextvideo: the video worker (media/mpvPlayer.py) plays whatever is queued
(`tblVideoMedia.que`) while the video play flag is 1, one mpv per video on `mpvsocket-video`; a video linked to the
current scene plays on that link's screen and volume, any other on screen 0. Skipping kills that mpv and the worker
starts the next one. Volume is the speakers' (music_tools.set_volume) and covers video too.
"""
import core.events as events
from media.music_tools import MusicToolError, _conn, _db, _norm, _plural, _scenes, _strip_filler

_FILLER_VIDEO = {'video', 'videos', 'clip', 'clips', 'movie', 'film', 'footage', 'screen', 'tv'}


def _want(text):
    words = [w for w in _strip_filler(text).split() if w not in _FILLER_VIDEO]
    return ' '.join(words) or _strip_filler(text)


def _downloaded(conn, ids):
    ids = [int(i) for i in ids]
    if not ids:
        return []
    ok = set()
    for start in range(0, len(ids), 500):
        part = ids[start:start + 500]
        ok.update(r[0] for r in conn.execute(
            f"SELECT video_ID FROM tblVideoMedia WHERE dnLoadStatus = 3 AND COALESCE(active,1) = 1 "
            f"AND video_ID IN ({','.join('?' * len(part))})", part))
    return [i for i in ids if i in ok]


def _scene_videos(conn, scene_id):
    return [r[0] for r in conn.execute("SELECT video_ID FROM tblVideoScene WHERE scene_ID = ? "
                                       "ORDER BY COALESCE(orderBy, 1e9), videoScene_ID", (scene_id,))]


def _video_playing():
    import sql
    return int(sql.appsettingFlagGet('currentvideo') or 0) > 0


def resolve_video(request):
    """(label, [video ids]) for a spoken request: a scene whose videos it names, a genre, a scene holding the words,
    then words in the video titles."""
    import media.smart_scenes as smart_scenes
    raw = _norm(request)
    if not raw:
        raise MusicToolError('Play which video?')
    want = _want(raw)
    db = _db()
    with _conn() as conn:
        rows = _scenes(conn)
        for cand in (raw, _strip_filler(raw), want):
            for sid, name in rows:
                if _norm(name) == cand:
                    ids = _scene_videos(conn, sid)
                    if _downloaded(conn, ids):
                        return f'the "{name}" videos', ids
        facets = smart_scenes.facet_options(db)
        for g in facets['genres']:
            if _norm(g['value']) == want or _norm(g['value']).rstrip('s') == want.rstrip('s'):
                ids = [i for i, _ in smart_scenes.match(db, {'media': ['video'], 'genres': [g['value']]})['video']]
                if _downloaded(conn, ids):
                    return f'{g["value"]} videos', ids
        for sid, name in sorted((r for r in rows if want and want in _norm(r[1])), key=lambda r: len(r[1])):
            ids = _scene_videos(conn, sid)
            if _downloaded(conn, ids):
                return f'the "{name}" videos', ids
        found = smart_scenes.match(db, {'media': ['video'], 'text': want})['video']
        ids = _downloaded(conn, [i for i, _ in found])
        if ids:
            names = dict(found)
            return (f'"{names[ids[0]]}"' if len(ids) == 1 else f'videos matching "{want}"'), ids
        with_video = [name for sid, name in rows if _downloaded(conn, _scene_videos(conn, sid))]
        titles = [r[0] for r in conn.execute(
            "SELECT COALESCE(NULLIF(displayName,''), title) FROM tblVideoMedia WHERE dnLoadStatus = 3 "
            "AND COALESCE(active,1) = 1 ORDER BY pTimes DESC LIMIT 8")]
    hints = with_video[:8] + titles
    raise MusicToolError(f'No video matches "{request}". Try one of: {", ".join(hints) or "no video is downloaded yet"}.')


def play_video(request, replace=True):
    """Queue the videos the request names; replace (default) swaps the video queue and cuts to them."""
    import sql
    label, ids = resolve_video(request)
    was_playing = _video_playing()
    with _conn() as conn:
        ids = _downloaded(conn, ids)
        if replace:
            conn.execute("UPDATE tblVideoMedia SET que = 0 WHERE que <> 0")
        for start in range(0, len(ids), 500):
            part = ids[start:start + 500]
            conn.execute(f"UPDATE tblVideoMedia SET que = 1 WHERE video_ID IN ({','.join('?' * len(part))})", part)
        conn.commit()
    sql.appsettingVideoPlayFlagUpdate(1)
    if replace and was_playing:
        sql.queueVideo_next()
    events.emit('queue', None)
    events.emit('nowplaying', None)
    verb = 'Playing' if replace else 'Added to the video queue:'
    return {'matched': label, 'videos': len(ids), 'replaced': bool(replace),
            'message': f'{verb} {label} ({_plural(len(ids), "video")}).'}


def skip_video():
    import sql
    playing = _video_playing()
    sql.appsettingVideoPlayFlagUpdate(1)
    sql.queueVideo_next()
    events.emit('nowplaying', None)
    return {'skipped': playing, 'message': 'Skipped to the next video.' if playing else 'No video was playing.'}


def _pause_video(on):
    from media.mpv_ipc import mpv_command
    if not mpv_command('video', f'set pause {"yes" if on else "no"}'):
        return {'paused': None, 'message': 'No video is playing.'}
    events.emit('nowplaying', None)
    return {'paused': on, 'message': 'Video paused.' if on else 'Video resumed.'}


def pause_video():
    return _pause_video(True)


def resume_video():
    return _pause_video(False)


def stop_video():
    """Video only: the video queue empties and the video closes (music, lights and the scene stay). The play flag
    goes to 0 first so the worker does not take the empty queue for the scene's end (which turns the lights off)."""
    import sql
    sql.appsettingVideoPlayFlagUpdate(0)
    with _conn() as conn:
        conn.execute("UPDATE tblVideoMedia SET que = 0 WHERE que <> 0")
        conn.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentvideo'")
        conn.commit()
    sql.queueVideo_next()
    events.emit('queue', None)
    events.emit('nowplaying', None)
    return {'message': 'Video stopped and the video queue cleared.'}

"""Music control for AI clients: the MCP server (integrations/mcp_server.py)
and anything else that wants to drive the music by name ("play jazz").

Plain functions over the same helpers the routers use (sql.py, extensions'
volume, media.mpv_ipc, media.smart_scenes) — no MCP import here, so a future
in-app assistant can call them directly. Every function returns a small
JSON-able dict with a human-readable `message` (a voice character reads it
out); a bad request raises MusicToolError with a message worth saying.

Music only: playing a playlist here never touches the lights, OBS, video or
the current scene — `play_scene` is the one call that does the full scene
activation, through the same lock the /activatescenes/ endpoint uses.
"""
import contextlib
import re
import sqlite3

import core.events as events

MAX_ROWS = 100
_FILLER = {'play', 'some', 'any', 'me', 'a', 'an', 'the', 'music', 'songs', 'song', 'tracks', 'track',
           'playlist', 'please', 'put', 'on', 'start', 'from', 'by', 'of', 'tunes', 'stuff'}
_DECADE_RX = re.compile(r"^(1[89]|20)?(\d)0s$")


class MusicToolError(ValueError):
    """A request the library cannot satisfy; the message is safe to show or say."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _db():
    import sql
    return sql.database


@contextlib.contextmanager
def _conn():
    conn = sqlite3.connect(_db(), timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def _downloaded_ids(conn, ids):
    """The ids that are downloaded and active (only those can play)."""
    ids = [int(i) for i in ids]
    if not ids:
        return []
    ok = set()
    for start in range(0, len(ids), 500):
        part = ids[start:start + 500]
        marks = ','.join('?' * len(part))
        ok.update(r[0] for r in conn.execute(
            f"SELECT song_ID FROM tblMusic WHERE dnLoadStatus = 3 AND COALESCE(active,1) = 1 "
            f"AND song_ID IN ({marks})", part))
    return [i for i in ids if i in ok]


def _scenes(conn):
    return conn.execute("SELECT scene_ID, COALESCE(sceneName,'') FROM tblScenes "
                        "WHERE scene_ID > 0 AND TRIM(COALESCE(sceneName,'')) <> '' ORDER BY sceneName").fetchall()


def _find_scene(conn, ref):
    """A playlist (scene) by id or name: exact name first, then one whose name
    contains the words (or is contained in them). Raises with the close names."""
    rows = _scenes(conn)
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        sid = int(ref)
        for r in rows:
            if r[0] == sid:
                return r
        raise MusicToolError(f'There is no playlist with id {sid}.')
    want = _norm(ref)
    if not want:
        raise MusicToolError('Which playlist?')
    exact = [r for r in rows if _norm(r[1]) == want]
    if exact:
        return exact[0]
    near = [r for r in rows if want in _norm(r[1]) or (_norm(r[1]) and _norm(r[1]) in want)]
    if len(near) == 1:
        return near[0]
    if near:
        near.sort(key=lambda r: abs(len(_norm(r[1])) - len(want)))
        return near[0]
    names = ', '.join(r[1] for r in rows[:15])
    raise MusicToolError(f'No playlist is called "{ref}". Playlists: {names or "none yet"}.')


def _norm(text):
    return ' '.join(str(text or '').lower().replace('_', ' ').split())


def _strip_filler(text):
    words = [w for w in re.split(r"[^\w']+", _norm(text)) if w]
    kept = [w for w in words if w not in _FILLER]
    return ' '.join(kept or words)


def _decade_of(text):
    """'80s', "80's", '1980s', '00s' -> '1980s' / '2000s' (media_facets' format), else None."""
    m = _DECADE_RX.match(str(text).replace(' ', '').replace("'", ''))
    if not m:
        return None
    century = m.group(1) or ('20' if m.group(2) in '012' else '19')
    return f'{century}{m.group(2)}0s'


def _queue(conn, song_ids, replace):
    """Put songs in the music queue. replace: the music queue becomes exactly
    these (and the song playing now fades out into them). Returns the count."""
    import sql
    ids = _downloaded_ids(conn, song_ids)
    if not ids:
        return 0
    was_playing = int(sql.appsettingFlagGet('currentsong') or 0) > 0
    if replace:
        conn.execute("UPDATE tblMusic SET que = 0 WHERE que <> 0")
    for start in range(0, len(ids), 500):
        part = ids[start:start + 500]
        conn.execute(f"UPDATE tblMusic SET que = 1 WHERE song_ID IN ({','.join('?' * len(part))})", part)
    conn.commit()
    sql.appsettingAudioPlayFlagUpdate(1)
    if replace and was_playing:
        sql.queue_next()
    events.emit('queue', None)
    return len(ids)


def _plural(n, word):
    return f'{n} {word}{"" if n == 1 else "s"}'


# ── reading ───────────────────────────────────────────────────────────────────

def is_paused():
    """True / False from the music mpv, None when no player answers."""
    from media.mpv_ipc import MpvClient
    try:
        client = MpvClient('music').connect(timeout=0.5)
    except Exception:
        return None
    try:
        return bool(client.command('get_property', 'pause', timeout=1.0))
    except Exception:
        return None
    finally:
        client.close()


def get_volume():
    from extensions import currentvolume
    try:
        return int(currentvolume())
    except Exception:
        return None


def now_playing():
    import sql
    np = sql.get_now_playing()
    song = np.get('song') or None
    scene_name = None
    scene_id = int(sql.appsettingGetCurrentScene() or 0)
    if scene_id > 0:
        with _conn() as conn:
            row = conn.execute("SELECT sceneName FROM tblScenes WHERE scene_ID = ?", (scene_id,)).fetchone()
            queued = conn.execute("SELECT COUNT(*) FROM tblMusic WHERE que <> 0").fetchone()[0]
            scene_name = row[0] if row else None
    else:
        with _conn() as conn:
            queued = conn.execute("SELECT COUNT(*) FROM tblMusic WHERE que <> 0").fetchone()[0]
    paused = is_paused() if song else None
    volume = get_volume()
    keep = bool(sql.appsettingGetKeepMusicPlaying())
    if song:
        msg = f'Playing "{song["name"]}"' + (' (paused)' if paused else '')
    else:
        msg = 'No music is playing'
    msg += f'; {_plural(queued, "song")} queued'
    if volume is not None:
        msg += f'; volume {volume}'
    return {'song': song['name'] if song else None, 'song_id': song['id'] if song else None,
            'paused': paused, 'volume': volume, 'queued_songs': queued, 'scene': scene_name,
            'keep_music_playing': keep, 'message': msg + '.'}


def list_playlists():
    import sql
    stats = sql.scene_media_stats()
    with _conn() as conn:
        rows = _scenes(conn)
        try:
            smart = {r[0] for r in conn.execute("SELECT scene_ID FROM tblSceneRules")}
        except sqlite3.OperationalError:
            smart = set()
    out = []
    for sid, name in rows:
        st = stats.get(sid, {})
        out.append({'id': sid, 'name': name, 'songs': st.get('songs', 0),
                    'play_time': st.get('play_time', ''), 'smart': sid in smart})
    with_music = [p for p in out if p['songs']]
    msg = (f'{_plural(len(with_music), "playlist")} with music: ' + ', '.join(p['name'] for p in with_music[:40]) + '.'
           if with_music else 'No playlist has music yet.')
    return {'playlists': out[:200], 'message': msg}


def get_playlist(playlist):
    with _conn() as conn:
        sid, name = _find_scene(conn, playlist)
        rows = conn.execute(
            "SELECT m.song_ID, COALESCE(NULLIF(m.displayName,''), m.song), ms.orderBy, ms.volume, ms.loops, "
            "m.dnLoadStatus FROM tblMusicScene ms JOIN tblMusic m ON m.song_ID = ms.song_ID "
            "WHERE ms.scene_ID = ? ORDER BY COALESCE(ms.orderBy, 1e9), ms.musicScene_ID", (sid,)).fetchall()
    songs = [{'id': r[0], 'name': r[1], 'order': r[2], 'volume': r[3], 'loops': r[4],
              'downloaded': r[5] == 3} for r in rows]
    return {'id': sid, 'name': name, 'songs': songs[:MAX_ROWS * 2],
            'message': f'Playlist "{name}" has {_plural(len(songs), "song")}.'}


def search_library(text, limit=25):
    import media.smart_scenes as smart_scenes
    text = _norm(text)
    if not text:
        raise MusicToolError('Search for what?')
    limit = max(1, min(int(limit or 25), MAX_ROWS))
    found = smart_scenes.match(_db(), {'media': ['music'], 'text': text})['music']
    with _conn() as conn:
        ok = set(_downloaded_ids(conn, [i for i, _ in found]))
    hits = [{'id': i, 'name': n} for i, n in found if i in ok]
    return {'songs': hits[:limit], 'total': len(hits),
            'message': f'{_plural(len(hits), "song")} match "{text}".'}


def library_facets():
    import media.smart_scenes as smart_scenes
    f = smart_scenes.facet_options(_db())
    top = lambda items, n: [{'value': x['value'], 'count': x['count']} for x in items[:n]]   # noqa: E731
    return {'genres': top(f['genres'], 40), 'artists': top(f['artists'], 40),
            'decades': top(f['decades'], 20),
            'kinds': [{'value': k['value'], 'label': k['label'], 'count': k['count']} for k in f['kinds']],
            'message': 'Genres: ' + ', '.join(g['value'] for g in f['genres'][:15]) + '.'}


# ── "play jazz" ───────────────────────────────────────────────────────────────

def resolve_request(request):
    """What a spoken request means in this library:
    (label, [song ids]) — a playlist name first, then a genre, an artist, a
    decade, a kind (mix / long track), then words in the titles."""
    import media.smart_scenes as smart_scenes
    raw = _norm(request)
    if not raw:
        raise MusicToolError('Play what?')
    want = _strip_filler(raw)
    db = _db()
    with _conn() as conn:
        rows = _scenes(conn)
        for cand in (raw, want):
            hit = [r for r in rows if _norm(r[1]) == cand]
            if hit:
                ids = [r[0] for r in conn.execute("SELECT song_ID FROM tblMusicScene WHERE scene_ID = ? "
                                                  "ORDER BY COALESCE(orderBy, 1e9)", (hit[0][0],))]
                if _downloaded_ids(conn, ids):
                    return f'playlist "{hit[0][1]}"', ids
    facets = smart_scenes.facet_options(db)
    rules = []
    for g in facets['genres']:
        if _norm(g['value']) == want or _norm(g['value']).rstrip('s') == want.rstrip('s'):
            rules.append((f'{g["value"]} genre', {'genres': [g['value']]}))
            break
    for a in facets['artists']:
        if _norm(a['value']) == want:
            rules.append((f'songs by {a["value"]}', {'artists': [a['value']]}))
            break
    dec = _decade_of(want)
    if dec:
        rules.append((f'songs from the {dec}', {'decades': [dec]}))
    for k in facets['kinds']:
        if want in (_norm(k['value']), _norm(k['value']) + 'es', _norm(k['value']) + 's', _norm(k['label'])):
            rules.append((_norm(k['label']), {'kinds': [k['value']]}))
    with _conn() as conn:
        for label, rule in rules:
            ids = [i for i, _ in smart_scenes.match(db, {'media': ['music'], **rule})['music']]
            if _downloaded_ids(conn, ids):
                return label, ids
        # playlists whose name holds the words ("jazz" -> "Smoky Jazz Club")
        near = [r for r in rows if want and want in _norm(r[1])]
        for sid, name in sorted(near, key=lambda r: len(r[1])):
            ids = [r[0] for r in conn.execute("SELECT song_ID FROM tblMusicScene WHERE scene_ID = ?", (sid,))]
            if _downloaded_ids(conn, ids):
                return f'playlist "{name}"', ids
        # genres / artists containing the words
        for g in facets['genres']:
            if want and want in _norm(g['value']):
                ids = [i for i, _ in smart_scenes.match(db, {'media': ['music'], 'genres': [g['value']]})['music']]
                if _downloaded_ids(conn, ids):
                    return f'{g["value"]} genre', ids
        ids = [i for i, _ in smart_scenes.match(db, {'media': ['music'], 'text': want})['music']]
        if _downloaded_ids(conn, ids):
            return f'songs matching "{want}"', ids
    hints = [r[1] for r in rows][:8] + [g['value'] for g in facets['genres'][:8]]
    raise MusicToolError(f'Nothing in the music library matches "{request}". '
                         f'Try one of: {", ".join(hints) or "nothing is downloaded yet"}.')


def play_music(request, replace=True):
    label, ids = resolve_request(request)
    with _conn() as conn:
        n = _queue(conn, ids, bool(replace))
    if not n:
        raise MusicToolError(f'Nothing in {label} is downloaded yet.')
    verb = 'Playing' if replace else 'Added to the queue:'
    return {'matched': label, 'songs': n, 'replaced': bool(replace),
            'message': f'{verb} {label} ({_plural(n, "song")}).'}


def queue_songs(song_ids, replace=False):
    if not song_ids:
        raise MusicToolError('Which songs? Give their ids from search_library.')
    with _conn() as conn:
        n = _queue(conn, song_ids, bool(replace))
    if not n:
        raise MusicToolError('None of those songs is downloaded.')
    return {'songs': n, 'replaced': bool(replace),
            'message': f'{"Playing" if replace else "Queued"} {_plural(n, "song")}.'}


def play_scene(scene):
    """The full scene: music, video, lights and the linked OBS scene."""
    from routers import public
    with _conn() as conn:
        sid, name = _find_scene(conn, scene)
    with public._activate_lock:
        public._activate_scene(sid)
    events.emit('scene', {'scene_id': sid})
    return {'id': sid, 'name': name, 'message': f'Scene "{name}" is on: music, video and lights.'}


# ── transport + volume ────────────────────────────────────────────────────────

def set_volume(level=None, change=None):
    from extensions import setvolume
    if level is None and change is None:
        raise MusicToolError('Give a level from 0 to 100, or a change such as -10.')
    current = get_volume()
    if level is None:
        if current is None:
            raise MusicToolError('The current volume cannot be read, so give a level instead of a change.')
        level = current + int(change)
    level = max(0, min(100, int(level)))
    setvolume(level)
    events.emit('nowplaying', None)
    return {'volume': level, 'previous': current, 'message': f'Volume is {level}.'}


def skip():
    import sql
    playing = int(sql.appsettingFlagGet('currentsong') or 0) > 0
    sql.appsettingAudioPlayFlagUpdate(1)
    sql.queue_next()
    events.emit('nowplaying', None)
    return {'skipped': playing, 'message': 'Skipped to the next song.' if playing else 'Nothing was playing.'}


def _pause(on):
    from media.mpv_ipc import mpv_command
    if not mpv_command('music', f'set pause {"yes" if on else "no"}'):
        return {'paused': None, 'message': 'The music player is not running.'}
    events.emit('nowplaying', None)
    return {'paused': on, 'message': 'Music paused.' if on else 'Music resumed.'}


def pause():
    return _pause(True)


def resume():
    return _pause(False)


def seek(seconds):
    from media.mpv_ipc import mpv_command
    s = int(seconds)
    if not mpv_command('music', f'seek {s}'):
        return {'message': 'The music player is not running.'}
    return {'seconds': s, 'message': f'Jumped {"forward" if s >= 0 else "back"} {abs(s)} seconds.'}


def stop_music():
    """Music only: the music queue empties and the song fades out (video,
    lights and the current scene stay)."""
    import sql
    with _conn() as conn:
        conn.execute("UPDATE tblMusic SET que = 0 WHERE que <> 0")
        conn.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentsong'")
        conn.commit()
    sql._music_stop()
    events.emit('queue', None)
    events.emit('nowplaying', None)
    return {'message': 'Music stopped and the music queue cleared.'}


def set_keep_music(on):
    import sql
    sql.appsettingSetKeepMusicPlaying(1 if on else 0)
    return {'keep_music_playing': bool(on),
            'message': 'Music keeps playing between scenes.' if on else 'Music stops with the scene.'}


# ── playlists ─────────────────────────────────────────────────────────────────

def _campaign_for_new():
    import sql
    try:
        cid = int(sql.appsettingGetCampaignFilter() or 0)
    except Exception:
        cid = 0
    return cid or 1


def create_playlist(name, song_ids=None, genres=None, artists=None, decades=None, text=None, campaign_id=None):
    """A plain playlist from song ids, or a smart one from a rule (every
    picked field must match: genres AND decades ...). Music only."""
    import media.smart_scenes as smart_scenes
    name = str(name or '').strip()[:80]
    if not name:
        raise MusicToolError('The playlist needs a name.')
    with _conn() as conn:
        if any(_norm(r[1]) == _norm(name) for r in _scenes(conn)):
            raise MusicToolError(f'A playlist called "{name}" already exists.')
    cid = int(campaign_id or 0) or _campaign_for_new()
    if song_ids:
        with _conn() as conn:
            ids = [i for i in dict.fromkeys(int(x) for x in song_ids)]
            known = {r[0] for r in conn.execute(
                f"SELECT song_ID FROM tblMusic WHERE song_ID IN ({','.join('?' * len(ids))})", ids)}
            ids = [i for i in ids if i in known]
            if not ids:
                raise MusicToolError('None of those song ids is in the library.')
            order = conn.execute("SELECT COALESCE(MAX(orderBy), 0) + 1 FROM tblScenes WHERE campaign_id = ?",
                                 (cid,)).fetchone()[0]
            sid = conn.execute("INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES (?, 1, ?, ?)",
                               (name, order, cid)).lastrowid
            conn.executemany("INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume, loops) "
                             "VALUES (?, ?, ?, 100, 0)", [(sid, i, n + 1) for n, i in enumerate(ids)])
            conn.commit()
        events.emit('scene', None)
        return {'id': sid, 'name': name, 'songs': len(ids), 'smart': False,
                'message': f'Made playlist "{name}" with {_plural(len(ids), "song")}.'}
    rule = {'media': ['music'], 'combine': 'all'}
    for key, val in (('genres', genres), ('artists', artists), ('decades', decades)):
        if val:
            rule[key] = [str(v) for v in (val if isinstance(val, list) else [val])]
    if decades:
        rule['decades'] = [_decade_of(_norm(d)) or str(d) for d in rule['decades']]
    if text:
        rule['text'] = str(text)
    if len(rule) == 2:
        raise MusicToolError('Give song ids, or what the playlist holds: genres, artists, decades or words.')
    if not smart_scenes.match(_db(), rule)['music']:
        raise MusicToolError('Nothing in the library matches that, so no playlist was made.')
    made = smart_scenes.create_scene(_db(), name, cid, rule)
    events.emit('scene', None)
    n = made['added'].get('music', 0) if isinstance(made.get('added'), dict) else 0
    return {'id': made['scene_id'], 'name': name, 'songs': n, 'smart': True,
            'message': f'Made smart playlist "{name}" with {_plural(n, "song")}; new downloads that match join it.'}


def add_to_playlist(playlist, song_ids):
    if not song_ids:
        raise MusicToolError('Which songs?')
    with _conn() as conn:
        sid, name = _find_scene(conn, playlist)
        have = {r[0] for r in conn.execute("SELECT song_ID FROM tblMusicScene WHERE scene_ID = ?", (sid,))}
        ids = [i for i in dict.fromkeys(int(x) for x in song_ids) if i not in have]
        known = {r[0] for r in conn.execute(
            f"SELECT song_ID FROM tblMusic WHERE song_ID IN ({','.join('?' * len(ids)) or 'NULL'})", ids)}
        ids = [i for i in ids if i in known]
        nxt = conn.execute("SELECT COALESCE(MAX(orderBy), 0) FROM tblMusicScene WHERE scene_ID = ?",
                           (sid,)).fetchone()[0]
        conn.executemany("INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume, loops) VALUES (?, ?, ?, 100, 0)",
                         [(sid, i, nxt + n + 1) for n, i in enumerate(ids)])
        conn.commit()
    events.emit('scene', None)
    return {'id': sid, 'name': name, 'added': len(ids),
            'message': f'Added {_plural(len(ids), "song")} to "{name}".'}


def remove_from_playlist(playlist, song_ids):
    if not song_ids:
        raise MusicToolError('Which songs?')
    ids = [int(x) for x in song_ids]
    with _conn() as conn:
        sid, name = _find_scene(conn, playlist)
        n = conn.execute(f"DELETE FROM tblMusicScene WHERE scene_ID = ? AND song_ID IN ({','.join('?' * len(ids))})",
                         [sid, *ids]).rowcount
        conn.commit()
    events.emit('scene', None)
    return {'id': sid, 'name': name, 'removed': n,
            'message': f'Removed {_plural(n, "song")} from "{name}".'}

"""AI control: media.music_tools ("play jazz" resolution, queue rules, volume)
and the /mcp server (the on/off switch, the token, JSON-RPC tool calls), plus
the Utilities settings endpoints. Nothing here may touch the real speakers or
players: volume, skip and fades are replaced by recorders."""
import sqlite3

import pytest

import core.config as config

MCP_HEADERS = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json',
               'MCP-Protocol-Version': '2025-06-18'}


@pytest.fixture()
def library(client, monkeypatch):
    """Two playlists, a Jazz genre and an 80s song in the session database;
    removed afterwards. Returns the ids."""
    import extensions
    import sql
    calls = {'volume': [], 'skips': 0, 'stops': 0}
    vol = {'v': 50}
    monkeypatch.setattr(extensions, 'currentvolume', lambda: vol['v'])

    def _set(v):
        calls['volume'].append(v)
        vol['v'] = v
    monkeypatch.setattr(extensions, 'setvolume', _set)
    monkeypatch.setattr(sql, 'queue_next', lambda: calls.__setitem__('skips', calls['skips'] + 1))
    monkeypatch.setattr(sql, '_music_stop', lambda: calls.__setitem__('stops', calls['stops'] + 1))
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    jazz = c.execute("INSERT INTO lutGenre(genre, active) VALUES ('Jazz', 1)").lastrowid

    def song(name, genre=None, ok=3):
        return c.execute("INSERT INTO tblMusic(path, song, displayName, active, genre, que, dnLoadStatus) "
                         "VALUES ('/m/', ?, ?, 1, ?, 0, ?)", (name + '.mp3', name, genre, ok)).lastrowid
    ids = {'blue': song('Blue in Green', jazz), 'take5': song('Take Five', jazz),
           'jig': song('Tavern Jig'), 'reel': song('Drunken Reel'), 'synth': song('Neon Drive 1984'),
           'pending': song('Not Yet Downloaded', jazz, ok=1)}
    tavern = c.execute("INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Tavern', 1, 1, 1)").lastrowid
    boss = c.execute("INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Boss Fight', 1, 2, 1)").lastrowid
    c.executemany("INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume, loops) VALUES (?, ?, ?, 100, 0)",
                  [(tavern, ids['jig'], 1), (tavern, ids['reel'], 2), (boss, ids['synth'], 1)])
    c.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentsong'")
    conn.commit()
    yield {**ids, 'tavern': tavern, 'boss': boss, 'calls': calls, 'vol': vol}
    c.execute("DELETE FROM tblMusicScene")
    c.execute("DELETE FROM tblSceneRules") if c.execute(
        "SELECT 1 FROM sqlite_master WHERE name='tblSceneRules'").fetchone() else None
    c.execute("DELETE FROM tblScenes WHERE scene_ID > 0")
    c.execute("DELETE FROM tblMusic")
    c.execute("DELETE FROM lutGenre WHERE genre_id = ?", (jazz,))
    conn.commit()
    conn.close()


def _queued():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[0] for r in conn.execute("SELECT song_ID FROM tblMusic WHERE que <> 0")}
    finally:
        conn.close()


# ── music_tools ───────────────────────────────────────────────────────────────

def test_play_by_playlist_name_replaces_the_queue(library):
    import media.music_tools as mt
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE tblMusic SET que = 1 WHERE song_ID = ?", (library['synth'],))
    conn.commit()
    conn.close()
    r = mt.play_music('the tavern playlist')
    assert r['matched'] == 'playlist "Tavern"'
    assert _queued() == {library['jig'], library['reel']}
    assert 'Tavern' in r['message'] and '2 songs' in r['message']


def test_play_jazz_by_genre_skips_undownloaded(library):
    import media.music_tools as mt
    r = mt.play_music('Play some jazz')
    assert r['matched'] == 'Jazz genre'
    assert _queued() == {library['blue'], library['take5']}


def test_play_by_decade_and_title_words(library):
    import media.music_tools as mt
    assert mt._decade_of('80s') == '1980s' and mt._decade_of("80's") == '1980s'
    assert mt._decade_of('00s') == '2000s' and mt._decade_of('1970s') == '1970s'
    assert mt._decade_of('jazz') is None
    r = mt.play_music('neon')
    assert r['matched'] == 'songs matching "neon"'
    assert _queued() == {library['synth']}


def test_append_keeps_the_queue_and_skips_only_on_replace(library):
    import media.music_tools as mt
    import sql
    sql.appsettingSet('currentsong', str(library['synth']))
    mt.play_music('tavern', replace=False)
    assert library['calls']['skips'] == 0
    mt.play_music('jazz', replace=False)
    assert _queued() == {library['jig'], library['reel'], library['blue'], library['take5']}
    mt.play_music('boss fight')
    assert _queued() == {library['synth']}
    assert library['calls']['skips'] == 1     # fades out of the old song into the new queue
    sql.appsettingSet('currentsong', '0')


def test_nothing_matches_names_what_exists(library):
    import media.music_tools as mt
    with pytest.raises(mt.MusicToolError) as e:
        mt.play_music('polka')
    assert 'Tavern' in str(e.value) and 'Jazz' in str(e.value)


def test_volume_level_change_and_clamp(library):
    import media.music_tools as mt
    assert mt.set_volume(change=-10)['volume'] == 40
    assert mt.set_volume(level=150)['volume'] == 100
    assert mt.set_volume(change=-500)['volume'] == 0
    assert library['calls']['volume'] == [40, 100, 0]
    with pytest.raises(mt.MusicToolError):
        mt.set_volume()


def test_pause_and_resume_are_explicit(library, monkeypatch):
    import media.mpv_ipc as mpv_ipc
    import media.music_tools as mt
    sent = []
    monkeypatch.setattr(mpv_ipc, 'mpv_command', lambda kind, cmd: sent.append((kind, cmd)) or True)
    mt.pause()
    mt.pause()
    mt.resume()
    assert sent == [('music', 'set pause yes'), ('music', 'set pause yes'), ('music', 'set pause no')]


def test_playlists_create_add_remove(library):
    import media.music_tools as mt
    names = {p['name']: p for p in mt.list_playlists()['playlists']}
    assert names['Tavern']['songs'] == 2
    made = mt.create_playlist('Chill', song_ids=[library['blue'], library['take5']])
    assert made['songs'] == 2 and not made['smart']
    with pytest.raises(mt.MusicToolError):
        mt.create_playlist('chill', song_ids=[library['blue']])
    assert mt.add_to_playlist('Chill', [library['jig'], library['blue']])['added'] == 1
    assert [s['id'] for s in mt.get_playlist('chill')['songs']] == [library['blue'], library['take5'], library['jig']]
    assert mt.remove_from_playlist(made['id'], [library['take5']])['removed'] == 1
    smart = mt.create_playlist('Jazz Only', genres=['Jazz'])
    assert smart['smart'] and smart['songs'] == 3      # links every match; only downloaded ones play


def test_stop_music_empties_only_the_music_queue(library):
    import media.music_tools as mt
    mt.play_music('tavern')
    mt.stop_music()
    assert _queued() == set() and library['calls']['stops'] == 1


# ── /mcp ──────────────────────────────────────────────────────────────────────

def _rpc(client, token, method, params=None, rid=1):
    h = dict(MCP_HEADERS)
    if token:
        h['Authorization'] = f'Bearer {token}'
    body = {'jsonrpc': '2.0', 'id': rid, 'method': method}
    if params is not None:
        body['params'] = params
    return client.post('/mcp', headers=h, json=body)


def test_mcp_is_off_by_default_and_needs_the_token(client):
    import integrations.mcp_server as m
    m.set_enabled(False)
    tok = m.new_token()
    r = _rpc(client, tok, 'tools/list')
    assert r.status_code == 403 and r.json()['code'] == 'mcp_off'
    m.set_enabled(True)
    try:
        assert _rpc(client, None, 'tools/list').status_code == 401
        assert _rpc(client, 'wrong', 'tools/list').status_code == 401
        r = _rpc(client, tok, 'tools/list')
        assert r.status_code == 200
        tools = {t['name']: t for t in r.json()['result']['tools']}
        assert {'play_music', 'set_volume', 'skip', 'pause', 'resume', 'now_playing'} <= set(tools)
        assert tools['remove_from_playlist']['annotations']['destructiveHint'] is True
        assert tools['stop_music']['annotations']['destructiveHint'] is False      # voice clients may stop
        assert tools['all_stop']['annotations']['destructiveHint'] is False
        assert tools['play_music']['annotations']['destructiveHint'] is False
        old = tok
        tok = m.new_token()
        assert _rpc(client, old, 'tools/list').status_code == 401
    finally:
        m.set_enabled(False)


def test_mcp_tool_call_plays_jazz(client, library):
    import integrations.mcp_server as m
    m.set_enabled(True)
    tok = m.new_token()
    try:
        r = _rpc(client, tok, 'tools/call', {'name': 'play_music', 'arguments': {'request': 'jazz'}})
        res = r.json()['result']
        assert res['isError'] is False and 'Jazz' in res['content'][0]['text']
        assert _queued() == {library['blue'], library['take5']}
        r = _rpc(client, tok, 'tools/call', {'name': 'play_music', 'arguments': {'request': 'polka'}})
        res = r.json()['result']
        assert res['isError'] is True and 'Nothing in the music library' in res['content'][0]['text']
    finally:
        m.set_enabled(False)


def test_mcp_settings_are_dm_only_and_show_the_token_once(client, dm_token, player_token):
    import integrations.mcp_server as m
    import os
    try:
        os.remove(os.path.join(config.INSTANCE_DIR, m.TOKEN_FILE))
    except OSError:
        pass
    assert client.post('/api/v1/mcp/settings', json={'enabled': True}).status_code in (401, 403)
    assert client.post('/api/v1/mcp/settings', json={'enabled': True},
                       headers={'Authorization': f'Bearer {player_token}'}).status_code == 403
    dm = {'Authorization': f'Bearer {dm_token}'}
    r = client.post('/api/v1/mcp/settings', json={'enabled': True}, headers=dm).json()
    assert r['enabled'] and r['has_token'] and m.token_ok(r['token'])
    again = client.post('/api/v1/mcp/settings', json={'enabled': True}, headers=dm).json()
    assert 'token' not in again                       # never shown a second time
    page = client.get('/api/v1/utilities', headers=dm).json()
    assert page['mcp']['enabled'] is True and 'token' not in page['mcp']
    new = client.post('/api/v1/mcp/token', headers=dm).json()['token']
    assert m.token_ok(new) and not m.token_ok(r['token'])
    off = client.post('/api/v1/mcp/settings', json={'enabled': False}, headers=dm).json()
    assert off['enabled'] is False


def test_mcp_accepts_numbers_sent_as_text(client, library):
    """qwen3.5 sends set_volume's change as "-10" (seen 2026-11-23): the schema coerces it."""
    import integrations.mcp_server as m
    m.set_enabled(True)
    tok = m.new_token()
    try:
        r = _rpc(client, tok, 'tools/call', {'name': 'set_volume', 'arguments': {'change': '-10'}})
        res = r.json()['result']
        assert res['isError'] is False and library['calls']['volume'] == [40]
    finally:
        m.set_enabled(False)


def test_all_stop_is_the_player_bar_button(library, monkeypatch):
    """Scene -1 through the activation lock (music + video + All Stop lights); Infinite Play keeps the music."""
    import media.music_tools as mt
    import sql
    from routers import public
    activated = []
    monkeypatch.setattr(public, '_activate_scene', lambda sid: activated.append(sid))
    sql.appsettingSetKeepMusicPlaying(0)
    r = mt.all_stop()
    assert activated == ['-1'] and r['music_kept'] is False and 'music and video stopped' in r['message']
    sql.appsettingSetKeepMusicPlaying(1)
    try:
        r = mt.all_stop()
        assert r['music_kept'] is True and 'Infinite Play' in r['message']
    finally:
        sql.appsettingSetKeepMusicPlaying(0)


def test_now_playing_names_the_song_and_artist(library, monkeypatch):
    """'What song is this?': the message carries the title and the artist (stored, or read off "Artist - Title")."""
    import media.music_tools as mt
    monkeypatch.setattr(mt, 'is_paused', lambda: False)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, title, uploader, artist) "
                     "VALUES ('music', ?, 'Take Five', 'Some Channel', 'Dave Brubeck')", (library['take5'],))
        conn.execute("UPDATE tblMusic SET displayName = 'Miles Davis - Blue in Green (Official Audio)' "
                     "WHERE song_ID = ?", (library['blue'],))
        conn.execute("UPDATE tblAppSettings SET value = ? WHERE name = 'currentsong'", (str(library['take5']),))
        conn.commit()
        np = mt.now_playing()
        assert (np['title'], np['artist']) == ('Take Five', 'Dave Brubeck')
        assert np['message'].startswith('Playing "Take Five" by Dave Brubeck;')

        conn.execute("UPDATE tblAppSettings SET value = ? WHERE name = 'currentsong'", (str(library['blue']),))
        conn.commit()
        np = mt.now_playing()
        assert (np['title'], np['artist']) == ('Blue in Green', 'Miles Davis')

        conn.execute("UPDATE tblAppSettings SET value = ? WHERE name = 'currentsong'", (str(library['jig']),))
        conn.commit()
        assert mt.now_playing()['message'].startswith('Playing "Tavern Jig" (artist unknown);')
    finally:
        conn.execute("DELETE FROM tblMediaMetadata WHERE media_type = 'music'")
        conn.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentsong'")
        conn.commit()
        conn.close()

"""ScenePlay's MCP server: music control for AI clients (Claude, a local
Ollama app, the 3dObject voice characters).

Streamable HTTP at /mcp on the app's own port, stateless + JSON replies.
OFF by default: Utilities -> AI Control turns it on (appsetting
`mcp_enabled`, read on every request, so the switch acts at once). Every
call needs `Authorization: Bearer <token>`; the token lives only in
instance/mcp_token (made / replaced from that card, shown once, never logged,
never in a URL) — the old playback URLs stay LAN-open as they always were,
but these tools also write playlists, so they always want the token.

The tools are thin wrappers over media.music_tools. Annotations matter to the
clients: the voice service hides every tool marked destructive (a misheard
word must never empty the queue or delete links).
"""
import hmac
import logging
import os
import secrets

import core.config as config

log = logging.getLogger('sceneplay.mcp')

SETTING = 'mcp_enabled'
TOKEN_FILE = 'mcp_token'
PATH = '/mcp'

INSTRUCTIONS = (
    "ScenePlay is the game-table jukebox and atmosphere controller. Playlists are called scenes. "
    "To play something by name, genre, artist or decade (\"play jazz\", \"some 80s music\", \"the tavern "
    "playlist\") call play_music with the words as said. play_music changes only the music; play_scene "
    "also changes the lights, video and OBS. Volume is 0-100: for \"a bit quieter\" use set_volume with "
    "change -10. Tool results carry a short `message` worth reading out.")


# ── switch + token ────────────────────────────────────────────────────────────

def enabled():
    from sql import appsettingGet
    try:
        return str(appsettingGet(SETTING, '0') or '0') == '1'
    except Exception:
        return False


def set_enabled(on):
    from sql import appsettingSet
    appsettingSet(SETTING, '1' if on else '0')


def _token_path():
    return os.path.join(config.INSTANCE_DIR, TOKEN_FILE)


def get_token():
    try:
        with open(_token_path(), encoding='utf-8') as f:
            tok = f.read().strip()
        return tok or None
    except OSError:
        return None


def new_token():
    """Make (or replace) the token; the old one stops working at once."""
    tok = secrets.token_urlsafe(32)
    os.makedirs(config.INSTANCE_DIR, exist_ok=True)
    path = _token_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(tok)
    return tok


def token_ok(given):
    want = get_token()
    return bool(want and given and hmac.compare_digest(str(given).encode(), want.encode()))


def available():
    try:
        import mcp.server.mcpserver  # noqa: F401
        return True
    except Exception:
        return False


# ── the server ────────────────────────────────────────────────────────────────

def _call(fn, *args, **kwargs):
    """Run one music tool in its own DB scope; a MusicToolError becomes a tool
    error whose text the client shows (or the character says)."""
    import core.db as _db
    from mcp.server.mcpserver.exceptions import ToolError
    from media.music_tools import MusicToolError
    token = _db.begin_request_scope()
    try:
        return fn(*args, **kwargs)
    except MusicToolError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        _db.end_request_scope(token)


def build_server():
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    import media.music_tools as mt
    from version import __version__

    srv = MCPServer('ScenePlay', instructions=INSTRUCTIONS, version=__version__)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
    write_idem = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
    destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

    @srv.tool(annotations=read)
    def now_playing() -> dict:
        """What is playing now: the song, paused or not, the volume (0-100), how many songs are queued
        and the active scene."""
        return _call(mt.now_playing)

    @srv.tool(annotations=write)
    def play_music(request: str, replace: bool = True) -> dict:
        """Play music by what was asked for: a playlist (scene) name, a genre, an artist, a decade
        ("80s"), "mixes", or words in song titles. Examples: "jazz", "tavern", "80s", "Miles Davis".
        replace=True (default) swaps the queue and fades into it; replace=False adds to the queue.
        Music only: lights, video and the scene stay as they are."""
        return _call(mt.play_music, request, replace)

    @srv.tool(annotations=write_idem)
    def set_volume(level: int | None = None, change: int | None = None) -> dict:
        """Set the speakers' volume: level 0-100, or change it by an amount (change=-10 is a bit
        quieter, change=10 a bit louder)."""
        return _call(mt.set_volume, level, change)

    @srv.tool(annotations=write)
    def skip() -> dict:
        """Skip the current song; the next one in the queue starts."""
        return _call(mt.skip)

    @srv.tool(annotations=write_idem)
    def pause() -> dict:
        """Pause the music (safe to call when already paused)."""
        return _call(mt.pause)

    @srv.tool(annotations=write_idem)
    def resume() -> dict:
        """Resume paused music (safe to call when already playing)."""
        return _call(mt.resume)

    @srv.tool(annotations=read)
    def list_playlists() -> dict:
        """Every playlist (scene) with its id, song count, play time and whether it is a smart playlist."""
        return _call(mt.list_playlists)

    @srv.tool(annotations=read)
    def get_playlist(playlist: str) -> dict:
        """The songs in one playlist, in order. playlist: its name or id."""
        return _call(mt.get_playlist, playlist)

    @srv.tool(annotations=read)
    def search_library(text: str, limit: int = 25) -> dict:
        """Find downloaded songs whose title, channel or artist contains the words. Returns ids for
        queue_songs, create_playlist and add_to_playlist."""
        return _call(mt.search_library, text, limit)

    @srv.tool(annotations=read)
    def library_facets() -> dict:
        """The genres, artists, decades and kinds in the music library, with counts — what play_music
        and create_playlist can pick from."""
        return _call(mt.library_facets)

    @srv.tool(annotations=write)
    def queue_songs(song_ids: list[int], replace: bool = False) -> dict:
        """Queue songs by id (from search_library or get_playlist). replace=True plays them now instead
        of the current queue."""
        return _call(mt.queue_songs, song_ids, replace)

    @srv.tool(annotations=write)
    def play_scene(scene: str) -> dict:
        """Start a whole scene by name or id: its music, video, lights and linked OBS scene. Use
        play_music when only the music should change."""
        return _call(mt.play_scene, scene)

    @srv.tool(annotations=write)
    def seek(seconds: int) -> dict:
        """Jump within the current song: positive forward, negative back."""
        return _call(mt.seek, seconds)

    @srv.tool(annotations=write_idem)
    def set_keep_music(on: bool) -> dict:
        """Keep music playing when a scene ends or changes (on), or let it stop with the scene (off)."""
        return _call(mt.set_keep_music, on)

    @srv.tool(annotations=write)
    def create_playlist(name: str, song_ids: list[int] | None = None, genres: list[str] | None = None,
                        artists: list[str] | None = None, decades: list[str] | None = None,
                        text: str | None = None) -> dict:
        """Make a new playlist. With song_ids: exactly those songs. Otherwise a smart playlist from a rule:
        every given field must match (genres AND decades ...); matching downloads join it later on their
        own. Decades look like "1980s". Use library_facets for the names."""
        return _call(mt.create_playlist, name, song_ids, genres, artists, decades, text)

    @srv.tool(annotations=write)
    def add_to_playlist(playlist: str, song_ids: list[int]) -> dict:
        """Add songs (by id) to the end of a playlist (by name or id)."""
        return _call(mt.add_to_playlist, playlist, song_ids)

    @srv.tool(annotations=destructive)
    def remove_from_playlist(playlist: str, song_ids: list[int]) -> dict:
        """Take songs (by id) out of a playlist. The songs stay in the library."""
        return _call(mt.remove_from_playlist, playlist, song_ids)

    @srv.tool(annotations=destructive)
    def stop_music() -> dict:
        """Stop the music and empty the music queue (video, lights and the scene stay). Prefer pause."""
        return _call(mt.stop_music)

    return srv


# ── ASGI gate in front of the SDK ─────────────────────────────────────────────

async def _json(send, status, body, extra=()):
    import json
    data = json.dumps(body).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json'),
                            (b'content-length', str(len(data)).encode()), *extra]})
    await send({'type': 'http.response.body', 'body': data})


class Gate:
    """The switch and the bearer check, then the SDK's handler."""

    def __init__(self, server):
        self.server = server

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return
        if not enabled():
            await _json(send, 403, {'error': 'The ScenePlay MCP server is turned off '
                                             '(Utilities -> AI Control).', 'code': 'mcp_off', 'detail': None})
            return
        auth = dict(scope.get('headers') or []).get(b'authorization', b'').decode('latin-1')
        given = auth[7:].strip() if auth[:7].lower() == 'bearer ' else ''
        if not token_ok(given):
            await _json(send, 401, {'error': 'A valid ScenePlay MCP token is required.',
                                    'code': 'mcp_token', 'detail': None},
                        [(b'www-authenticate', b'Bearer realm="ScenePlay MCP"')])
            return
        await self.server.session_manager.handle_request(scope, receive, send)


def attach(app):
    """Add /mcp to the app (before the SPA catch-all). The SDK's session
    manager is started by the app lifespan (`app.state.mcp`). Missing SDK:
    log once and leave /mcp out."""
    if not available():
        log.info('MCP SDK not installed: /mcp is off (pip install "mcp~=2.3")')
        app.state.mcp = None
        return
    from mcp.server.transport_security import TransportSecuritySettings
    srv = build_server()
    # Host/Origin checks off: the box is reached by LAN IPs, hotspot and
    # mDNS names; the bearer token (which a rebinding page cannot know) is the guard.
    srv.streamable_http_app(streamable_http_path=PATH, stateless_http=True, json_response=True,
                            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.state.mcp = srv
    app.router.add_route(PATH, Gate(srv), include_in_schema=False)

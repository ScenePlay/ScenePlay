"""A camera tile is TWO OBS sources: the bare feed, and the name strip above it.

It used to be one source whose page framed the feed. That is unfixable over
plain http: an https iframe inside an http parent is not a secure context, so
WebRTC never starts and vdo.ninja renders nothing. Measured inside OBS itself —
the same view URL shows the camera as a top-level source and is black one
iframe deep, while a framed example.com renders fine. &cleanoutput then hides
the error, so the only symptom is a silent black rectangle.

These lock in the split, because the failure it fixes is invisible: every
source is present, enabled and correctly sized while showing nothing.
"""
import pytest

from core.db import db
from models.ttrpg import tblCharacters


@pytest.fixture()
def page_app(legacy_app):
    """The real router through the session TestClient: the tile/card pages
    are token-gated standalone files, so no login is needed."""
    return legacy_app


@pytest.fixture()
def settings(app, monkeypatch):
    """Same reason as test_obs_feed: routers.obs holds its own binding."""
    store = {}
    import routers.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _char(**over):
    base = dict(character_id=7, user_id=1, name='Kara', level=1,
                hp_current=5, hp_max=5, created_at='2026-01-01 00:00:00')
    base.update(over)
    return tblCharacters(**base)


class TestTilePlan:
    def test_camera_tile_is_feed_plus_strip(self, app, settings):
        """The player's own source is the BARE feed — never the tile page."""
        import routers.obs as ro
        c = _char(video_stream_id='abc123')
        url, strip = ro._tile_plan(c, presence={}, overrides=set())
        assert url == c.video_view_url()
        assert url.startswith('https://vdo.ninja/')
        # The thing that was broken: the source must not be our page framing
        # the feed.
        assert '/tile/' not in url
        assert strip is not None and strip.endswith('&strip=1')

    def test_pinned_player_keeps_the_feed_as_their_source(self, app, settings):
        """THE audio rule: pinning someone to their card must not tear down
        their WebRTC connection, or it cuts their microphone mid-sentence.
        The card is drawn OVER the still-running camera instead."""
        import routers.obs as ro
        c = _char(video_stream_id='abc123')
        url, overlay = ro._tile_plan(c, presence={}, overrides={7})
        assert url == c.video_view_url(), 'the feed must keep running'
        assert '/card/' in overlay
        assert 'over=1' in overlay, 'a see-through card would show the camera'

    def test_stale_feed_also_keeps_the_source(self, app, settings, monkeypatch):
        """Same for a player the relay stopped hearing from: their picture is
        replaced, their audio is not."""
        import routers.obs as ro
        monkeypatch.setattr(ro, '_feed_state', lambda *a, **k: 'stale')
        c = _char(video_stream_id='abc123')
        url, overlay = ro._tile_plan(c, presence={}, overrides=set())
        assert url == c.video_view_url()
        assert 'over=1' in overlay

    def test_no_feed_configured_falls_back_to_card(self, app, settings):
        """Nothing to keep alive, so the card IS the source and needs no
        overlay above it."""
        import routers.obs as ro
        c = _char(video_stream_id='')
        url, overlay = ro._tile_plan(c, presence={}, overrides=set())
        assert '/card/' in url
        assert 'over=1' not in url, 'nothing behind it to hide'
        assert overlay is None

    def test_overlay_source_is_managed(self, app, settings):
        """Pruning and the reload-all sweep only touch prefixed sources; an
        overlay that misses the prefix would be orphaned in the scene."""
        import routers.obs as ro
        c = _char(video_stream_id='abc123')
        name = ro._overlay_source_name_for(c)
        assert name.startswith(ro._MANAGED_PREFIXES)
        assert name != ro._source_name_for(c)


class TestTileAudio:
    """Where each camera source's sound goes in the OBS mixer."""

    @pytest.fixture()
    def obs(self, monkeypatch):
        """Record what would be asked of OBS."""
        import integrations.obs_ws as obs_ws
        calls = {'mute': [], 'monitor': []}
        monkeypatch.setattr(obs_ws, 'set_input_mute',
                            lambda n, m, **k: calls['mute'].append((n, m)))
        monkeypatch.setattr(obs_ws, 'set_audio_monitor',
                            lambda n, t, **k: calls['monitor'].append((n, t)))
        # The fader is the third call every build makes; not under test here.
        monkeypatch.setattr(obs_ws, 'set_input_volume', lambda n, level, **k: None)
        return calls

    def test_dm_tile_is_muted_by_default(self, app, settings, obs):
        """The DM's tile is their own mic returning to them — unmuted it
        doubles their voice on the broadcast and can howl when monitored."""
        import routers.obs as ro
        dm = _char(character_id=ro.DM_TILE_ID, name='DM')
        ro._apply_tile_audio('DM - DM Cam', dm, [])
        assert obs['mute'] == [('DM - DM Cam', True)]

    def test_dm_tile_can_be_unmuted(self, app, settings, obs):
        import routers.obs as ro
        settings['obs_dm_audio'] = '1'
        dm = _char(character_id=ro.DM_TILE_ID, name='DM')
        ro._apply_tile_audio('DM - DM Cam', dm, [])
        assert obs['mute'] == [('DM - DM Cam', False)]

    def test_players_are_unmuted_unless_the_dm_muted_them(self, app, settings,
                                                          obs):
        import routers.obs as ro
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['mute'] == [('Player - Kara Cam', False)]

    def test_a_dm_muted_player_stays_muted_through_a_build(self, app, settings,
                                                           obs):
        """The mute is persisted, not just pushed at OBS: builds re-assert
        every tile's audio, so a mute living only in OBS would silently lift
        on the next rebuild — noticed on air."""
        import routers.obs as ro
        settings['obs_muted_ids'] = '7'
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['mute'] == [('Player - Kara Cam', True)]

    def test_monitoring_is_off_by_default(self, app, settings, obs):
        """Off still reaches the stream — it only decides whether the DM hears
        it locally, and most tables are already on a voice call."""
        import integrations.obs_ws as obs_ws
        import routers.obs as ro
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['monitor'] == [('Player - Kara Cam', obs_ws.MONITOR_OFF)]

    def test_monitoring_can_be_turned_on(self, app, settings, obs):
        import integrations.obs_ws as obs_ws
        import routers.obs as ro
        settings['obs_feed_monitor'] = '1'
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['monitor'] == [('Player - Kara Cam', obs_ws.MONITOR_ROOM)]

    def test_missing_monitor_device_does_not_fail_the_build(
            self, app, settings, obs, monkeypatch):
        """OBS with no monitoring device rejects the call. The feed still
        reaches the stream, so a scene build must not die over it."""
        import integrations.obs_ws as obs_ws
        import routers.obs as ro

        def boom(*a, **k):
            raise obs_ws.ObsRejected(600, 'no monitoring device')
        monkeypatch.setattr(obs_ws, 'set_audio_monitor', boom)
        warnings = []
        ro._apply_tile_audio('Player - Kara Cam', _char(), warnings)
        assert warnings == []


class TestStripPage:
    """The tile is one standalone page for both modes: the strip-only render
    (transparent, no framed feed) and the framed one are decided by the JS
    from ?strip=1, and the feed URL rides the state poll it does its own
    build from."""

    def _get(self, page_app, settings, strip):
        import routers.obs as ro
        settings['obs_dm_stream_id'] = 'abc123'
        settings['obs_dm_enabled'] = '1'
        tok = ro._card_token(ro.DM_TILE_ID)
        q = f'?t={tok}' + ('&strip=1' if strip else '')
        r = page_app.test_client().get('/ttrpg/obs/tile/dm' + q)
        assert r.status_code == 200, r.status_code
        return r.get_data()

    def test_page_never_frames_the_feed_in_markup(self, page_app, settings):
        """No <iframe> in the file: the feed is only framed by JS, and only
        outside strip mode — the framed feed is what was black in OBS."""
        body = self._get(page_app, settings, strip=True)
        assert b'<iframe' not in body, 'framing the feed is what was black'
        assert b"OBS.q.get('strip') === '1'" in body
        assert b'html.strip, html.strip body { background: transparent; }' in body, \
            'an opaque strip would hide the camera source underneath'
        # It is still the character strip, not an empty page.
        assert b'id="strip"' in body

    def test_state_carries_the_feed_for_the_framed_mode(self, page_app, settings):
        """Unchanged for an https parent — the relay serves this page too:
        the page frames feed_url from the state when ?strip is absent."""
        import routers.obs as ro
        settings['obs_dm_stream_id'] = 'abc123'
        settings['obs_dm_enabled'] = '1'
        tok = ro._card_token(ro.DM_TILE_ID)
        d = page_app.test_client().get(f'/ttrpg/obs/card/dm/state?t={tok}').get_json()
        assert d['feed_url'].startswith('https://vdo.ninja/')
        assert d['is_dm'] is True and d['poll_s'] >= 2
        body = self._get(page_app, settings, strip=False)
        assert b"f.src = d.feed_url" in body


class TestCardPage:
    def _get(self, page_app, settings, over):
        import routers.obs as ro
        settings['obs_dm_enabled'] = '1'
        tok = ro._card_token(ro.DM_TILE_ID)
        q = f'?t={tok}' + ('&over=1' if over else '')
        r = page_app.test_client().get('/ttrpg/obs/card/dm' + q)
        assert r.status_code == 200, r.status_code
        return r.get_data()

    def test_overlay_card_is_opaque(self, page_app, settings):
        """A see-through card would let the camera it is hiding show around
        the panel's edges: ?over=1 puts the opaque class on the page."""
        body = self._get(page_app, settings, over=True)
        assert b"OBS.q.get('over') === '1'" in body
        assert b'html.opaque, html.opaque body { background: var(--base-solid, #14151b); }' in body

    def test_overlay_card_does_not_claim_there_is_no_camera(self, page_app, settings):
        """It is covering a camera that is still running and still audible:
        the "no camera" label is only unhidden when the card IS the source."""
        body = self._get(page_app, settings, over=True)
        assert b'<div class="nocam" id="pc-nocam" hidden>' in body
        assert b"else document.getElementById('pc-nocam').hidden = false;" in body

    def test_standalone_card_stays_transparent(self, page_app, settings):
        """As the source itself it composites over the scene background."""
        body = self._get(page_app, settings, over=False)
        assert b'background: transparent;' in body
        assert b'no camera' in body

"""The OBS browser-source overlays (tile / card / panel / map) after the port.

They keep their exact URLs and `?t=` HMAC gate — OBS scene collections carry
those URLs — and are served as standalone files from web/obs, with everything
the Jinja versions injected now riding the /state poll. Nothing under
/ttrpg/obs may ever be cached.
"""
import hashlib
import hmac
import os

import pytest

import core.config as config
from core.db import db


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routers.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    sets = lambda name, value: store.__setitem__(name, str(value))  # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    monkeypatch.setattr(sql, 'appsettingSet', sets)
    monkeypatch.setattr(ro, 'appsettingSet', sets)
    return store


@pytest.fixture()
def c(legacy_app, settings):
    settings['obs_dm_enabled'] = '1'
    return legacy_app.test_client()


def _char(cid=7, portrait=''):
    from models.ttrpg import tblCharacters
    ch = tblCharacters(character_id=cid, user_id=1, name='Kara', level=1,
                       hp_current=5, hp_max=10, ac=14, portrait_path=portrait,
                       created_at='2026-01-01 00:00:00')
    db.session.add(ch)
    db.session.commit()
    return ch


NO_STORE = 'no-store, no-cache, must-revalidate, max-age=0'


class TestTokenDerivation:
    """Byte-identical to routes/obs.py: HMAC-SHA256 of the app secret over
    'obs-card:<id>' / 'obs-panel' / 'obs-map', hex, first 32 chars. Every
    browser-source URL saved inside an OBS scene collection carries one."""

    @staticmethod
    def _flask(msg):
        key = (config.SECRET_KEY or '').encode() or b'sceneplay'
        return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()[:32]

    def test_card_token_matches_the_flask_formula(self):
        import routers.obs as ro
        assert ro._card_token(7) == self._flask('obs-card:7')
        assert ro._card_token(ro.DM_TILE_ID) == self._flask('obs-card:-1')

    def test_panel_and_map_tokens_match(self):
        import routers.obs as ro
        assert ro._panel_token() == self._flask('obs-panel')
        assert ro._map_token() == self._flask('obs-map')

    def test_tokens_are_bound_to_the_secret(self, monkeypatch):
        import routers.obs as ro
        before = ro._map_token()
        monkeypatch.setattr(config, 'SECRET_KEY', 'something-else')
        assert ro._map_token() != before
        assert len(ro._map_token()) == 32


class TestGate:
    @pytest.mark.parametrize('path', ['/ttrpg/obs/map', '/ttrpg/obs/map/state', '/ttrpg/obs/map/floorplan',
                                      '/ttrpg/obs/map/textures', '/ttrpg/obs/panel', '/ttrpg/obs/panel/state',
                                      '/ttrpg/obs/card/dm', '/ttrpg/obs/card/dm/state', '/ttrpg/obs/tile/dm',
                                      '/ttrpg/obs/card/7', '/ttrpg/obs/card/7/state', '/ttrpg/obs/tile/7'])
    def test_no_token_is_403(self, c, path):
        for q in ('', '?t=', '?t=wrong', '?t=%E2%80%A6'):
            r = c.get(path + q)
            assert r.status_code == 403, (path, q, r.status_code)
            assert r.headers['cache-control'] == NO_STORE

    def test_a_players_token_does_not_open_another_card(self, c):
        import routers.obs as ro
        _char(7)
        _char(8)
        assert c.get(f'/ttrpg/obs/card/8?t={ro._card_token(7)}').status_code == 403
        assert c.get(f'/ttrpg/obs/card/8/state?t={ro._card_token(8)}').status_code == 200

    def test_unknown_character_with_a_valid_token_is_404(self, c):
        import routers.obs as ro
        assert c.get(f'/ttrpg/obs/card/99?t={ro._card_token(99)}').status_code == 404
        assert c.get(f'/ttrpg/obs/tile/99?t={ro._card_token(99)}').status_code == 404


class TestPagesAreTheStandaloneFiles:
    def _file(self, name):
        with open(os.path.join(config.WEB_DIR, 'obs', name), encoding='utf-8') as f:
            return f.read()

    @pytest.mark.parametrize('path,fname', [
        ('/ttrpg/obs/map', 'map.html'), ('/ttrpg/obs/panel', 'panel.html'),
        ('/ttrpg/obs/card/dm', 'card.html'), ('/ttrpg/obs/tile/dm', 'tile.html'),
    ])
    def test_serves_the_web_obs_file(self, c, path, fname):
        import routers.obs as ro
        tok = {'map.html': ro._map_token(), 'panel.html': ro._panel_token()}.get(fname, ro._card_token(ro.DM_TILE_ID))
        r = c.get(f'{path}?t={tok}')
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/html')
        assert r.headers['cache-control'] == NO_STORE
        assert r.headers['pragma'] == 'no-cache'
        assert r.get_data(as_text=True) == self._file(fname)

    def test_player_pages_too(self, c):
        import routers.obs as ro
        _char(7)
        assert c.get(f'/ttrpg/obs/card/7?t={ro._card_token(7)}').get_data(as_text=True) == self._file('card.html')
        assert c.get(f'/ttrpg/obs/tile/7?t={ro._card_token(7)}&strip=1').get_data(as_text=True) == self._file('tile.html')

    def test_no_jinja_and_no_flask_paths(self):
        for name in ('card.html', 'tile.html', 'panel.html', 'map.html', 'overlay_common.js'):
            src = self._file(name)
            for needle in ('{{', '{%', 'url_for', 'static/scripts/'):
                assert needle not in src, (name, needle)

    def test_pages_derive_their_urls_from_the_location(self):
        """No baked-in state URL: the page polls its own path + /state with
        the same token, the map's siblings likewise, the 3D viewer from /shared."""
        common = self._file('overlay_common.js')
        assert "'/state?t='" in common
        assert 'tile' in common and '/card/$1' in common
        assert "'/shared/three.min.js'" in self._file('map.html')
        assert "'/shared/battlemap3d.js'" in self._file('map.html')
        for name in ('card.html', 'tile.html', 'panel.html', 'map.html'):
            assert '/obs/overlay_common.js' in self._file(name)


class TestStateShapes:
    def test_card_state_carries_what_the_page_used_to_get_from_jinja(self, c):
        import routers.obs as ro
        _char(7, portrait='kara.png')
        d = c.get(f'/ttrpg/obs/card/7/state?t={ro._card_token(7)}').get_json()
        assert d['name'] == 'Kara' and d['hp_current'] == 5 and d['hp_max'] == 10
        assert d['hp_pct'] == 50 and d['ac'] == 14 and d['conditions'] == []
        assert d['is_dm'] is False
        assert d['portrait_url'] == '/static/uploads/portraits/kara.png'
        assert d['feed_url'] == ''
        assert d['poll_s'] == ro.CARD_POLL_DEFAULT
        assert set(d['theme']) >= {'accent', 'base', 'base2', 'dir', 'bezel', 'card', 'tile', 'dm_icon', 'dm_title'}

    def test_dm_card_state(self, c, settings):
        import routers.obs as ro
        settings['obs_dm_stream_id'] = 'abc123'
        settings['obs_card_poll_s'] = '30'
        d = c.get(f'/ttrpg/obs/card/dm/state?t={ro._card_token(ro.DM_TILE_ID)}').get_json()
        assert d['is_dm'] is True and d['hp_max'] == 0 and d['portrait_url'] == ''
        assert d['feed_url'].startswith('https://vdo.ninja/?view=abc123')
        assert d['poll_s'] == 30.0

    def test_panel_state_carries_modes_and_poll(self, c, settings):
        import routers.obs as ro
        settings['obs_panel_poll_s'] = '7'
        d = c.get(f'/ttrpg/obs/panel/state?t={ro._panel_token()}').get_json()
        assert d['card_modes'] == ['intermission', 'post', 'pre']
        assert d['modes'] == list(ro.PANEL_MODES)
        assert d['poll_s'] == 7.0
        assert d['canvas_w'] == 1920 and d['canvas_h'] == 1080
        for key in ('title_rect', 'panel_rect', 'dice_rect', 'bg_url', 'title', 'session', 'turn',
                    'info_lines', 'rolls', 'pre', 'intermission', 'post', 'image_fraction', 'theme',
                    'dice_popover', 'show_notes'):
            assert key in d, key

    def test_map_state_idle_without_a_live_map(self, c):
        import routers.obs as ro
        d = c.get(f'/ttrpg/obs/map/state?t={ro._map_token()}').get_json()
        assert d == {'live': False, 'title': {'image_url': '', 'campaign': '', 'session': ''}}

    def test_map_state_live(self, c):
        import routers.obs as ro
        from models.ttrpg import tblSessions, tblBattleMaps, tblBattleMapTokens
        _char(7)
        s = tblSessions(session_id=3, title='Night 3', status='active', created_at='2026-01-01 00:00:00')
        db.session.add(s)
        db.session.flush()
        bm = tblBattleMaps(map_id=5, session_id=3, name='Crypt', grid_cols=10, grid_rows=8,
                           bg_image='crypt.png', is_active=1, created_at='2026-01-01 00:00:00')
        db.session.add(bm)
        db.session.add(tblBattleMapTokens(map_id=5, entity_type='player', entity_id=7, col=2, row=3,
                                          updated_at='2026-01-01 00:00:01'))
        db.session.commit()
        d = c.get(f'/ttrpg/obs/map/state?t={ro._map_token()}').get_json()
        assert d['live'] is True and d['map_id'] == 5
        assert d['bg_url'] == '/static/uploads/battlemaps/crypt.png'
        assert d['cols'] == 10 and d['rows'] == 8
        assert [t['name'] for t in d['tokens']] == ['Kara']
        assert d['mode'] in ro.MAP_MODES and d['three_d_ready'] is False
        assert d['zoom'] == {'on': True, 'max': 2.2, 'hold_s': 6.0}
        for key in ('effects', 'fog', 'through', 'through_token_id', 'focus_token_id', 'look_at',
                    'map_name', 'collapse', 'floorplan_version', 'doors', 'movement_scale'):
            assert key in d, key
        fp = c.get(f'/ttrpg/obs/map/floorplan?t={ro._map_token()}&map_id=5').get_json()
        assert fp == {'ok': True, 'version': None, 'floorplan': None}
        tx = c.get(f'/ttrpg/obs/map/textures?t={ro._map_token()}').get_json()
        assert tx['ok'] is True and isinstance(tx['textures'], list)


class TestNoStoreEverywhere:
    def test_api_and_state_answers_are_never_cacheable(self, legacy_app, settings):
        from models.user import tblUsers
        import routers.obs as ro
        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm)
        db.session.commit()
        with legacy_app.test_client(user=dm) as c:
            for path in ('/ttrpg/obs/api/state', '/ttrpg/obs/api/health', '/ttrpg/obs/api/closeups',
                         f'/ttrpg/obs/panel/state?t={ro._panel_token()}'):
                r = c.get(path)
                assert r.status_code == 200, path
                assert r.headers['cache-control'] == NO_STORE, path
            r = c.post('/ttrpg/obs/api/map-mode', json={'mode': '2d'})
            assert r.get_json() == {'ok': True, 'mode': '2d', 'unpinned': False}
            assert r.headers['cache-control'] == NO_STORE

    def test_the_spa_feed_page_is_not_swept_up(self, client):
        """/ttrpg/obs/feed/<id> is an SPA view: the shell keeps its own policy."""
        r = client.get('/ttrpg/obs/feed/1', headers={'Accept': 'text/html'})
        assert r.status_code == 200 and '/app/main.js' in r.text
        assert 'no-store' not in r.headers.get('cache-control', '')


class TestPageData:
    def test_broadcast_page_data_has_every_key_the_template_reads(self, legacy_app, settings):
        from models.user import tblUsers
        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm)
        db.session.commit()
        with legacy_app.test_client(user=dm) as c:
            d = c.get('/api/v1/obs/page').get_json()
        for key in ('cfg', 'snap', 'rows', 'scene_rows', 'problems', 'dm_enabled', 'dm_id',
                    'map_token', 'map_preview_url', 'has_party', 'obs_servers', 'music_auto'):
            assert key in d, key
        assert d['map_preview_url'] == f"/ttrpg/obs/map?t={d['map_token']}"
        cfg = d['cfg']
        for key in ('enabled', 'host', 'port', 'has_password', 'transition', 'transition_ms', 'group_scene',
                    'auto_return_s', 'scene_link', 'map_scene', 'panel_on', 'panel_side', 'panel_fraction',
                    'title_h', 'panel_title', 'info_text', 'panel_notes', 'yt', 'portal_url', 'vdo_room',
                    'room_audio_only', 'room_videobitrate', 'room_join_url', 'accent', 'base', 'base2',
                    'base_dir', 'bezel', 'bezel_shapes', 'plate', 'plate2', 'plate_dir', 'card_design',
                    'tile_design', 'dm_icon', 'dm_icons', 'dm_title', 'theme_own', 'music_transport',
                    'music_resolved', 'music_forced', 'music_label', 'music_push', 'music_cable', 'music_out',
                    'music_outs', 'music_label_opts', 'obs_local', 'rig', 'dm_mic_label', 'dm_mic_hint',
                    'card_base', 'card_base_lan', 'card_base_loopback', 'card_base_suggested',
                    'card_base_stale', 'panel_poll', 'dice_autohide', 'pre', 'intermission', 'post', 'images',
                    'title_positions', 'map_mode', 'map_zoom', 'map_zoom_max', 'map_zoom_hold', 'card_poll',
                    'tile_anim_ms', 'boot_tripped', 'last_error'):
            assert key in cfg, key
        # first visit auto-fills the page address from the DM's own request
        assert settings['obs_card_base'].startswith('http')
        assert [i['slot'] for i in cfg['images']] == ['title', 'party_bg', 'intermission', 'post', 'yt_thumb']

    def test_page_data_is_dm_only(self, legacy_app):
        from models.user import tblUsers
        pl = tblUsers(username='pl', display_name='PL', password_hash='x',
                      role='player', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(pl)
        db.session.commit()
        with legacy_app.test_client(user=pl) as c:
            r = c.get('/api/v1/obs/page')
            assert r.status_code == 403 and r.get_json()['code'] == 'dm_required'
            assert c.get('/ttrpg/obs/api/state').status_code == 403
        assert legacy_app.test_client().get('/api/v1/obs/page').status_code == 401

    def test_feed_page_data_and_ownership(self, legacy_app, settings):
        from models.user import tblUsers
        from models.ttrpg import tblCharacters
        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        p1 = tblUsers(username='p1', display_name='P1', password_hash='x',
                      role='player', active=1, created_at='2026-01-01 00:00:00')
        p2 = tblUsers(username='p2', display_name='P2', password_hash='x',
                      role='player', active=1, created_at='2026-01-01 00:00:00')
        db.session.add_all([dm, p1, p2])
        db.session.commit()
        ch = tblCharacters(character_id=7, user_id=p1.user_id, name='Kara', level=1, hp_current=5,
                           hp_max=10, created_at='2026-01-01 00:00:00')
        db.session.add(ch)
        db.session.commit()
        with legacy_app.test_client(user=p1) as c:
            d = c.get('/api/v1/obs/feed/7').get_json()
            assert d['char'] == {'character_id': 7, 'name': 'Kara'}
            assert d['is_dm'] is False and d['is_dm_tile'] is False
            assert d['push_url'].startswith('https://vdo.ninja/?push=')
            assert d['save_url'] == '/ttrpg/obs/feed/7' and d['back_url'] == '/ttrpg/my-character'
            for key in ('view_url', 'qr_svg', 'portal_url', 'portal_qr', 'player_username'):
                assert key in d, key
            old = d['push_url']
            r = c.post('/ttrpg/obs/feed/7', data={'action': 'regenerate'})
            assert r.status_code == 200 and 'New camera link' in r.get_json()['message']
            assert c.get('/api/v1/obs/feed/7').get_json()['push_url'] != old
        with legacy_app.test_client(user=p2) as c:
            assert c.get('/api/v1/obs/feed/7').status_code == 403
            assert c.post('/ttrpg/obs/feed/7', data={'action': 'save'}).status_code == 403
        with legacy_app.test_client(user=dm) as c:
            d = c.get('/api/v1/obs/feed/7').get_json()
            assert d['is_dm'] is True and d['player_username'] == 'p1'
            d = c.get('/api/v1/obs/feed/dm').get_json()
            assert d['is_dm_tile'] is True and d['char']['character_id'] == -1
            assert d['save_url'] == '/ttrpg/obs/feed/dm' and d['back_url'] == '/ttrpg/obs'
            assert c.get('/api/v1/obs/feed/99').status_code == 404
        with legacy_app.test_client(user=p1) as c:
            assert c.get('/api/v1/obs/feed/dm').status_code == 403

"""Texture library endpoints: manifest union (builtin + DB), upload/paste
validation, slug collisions, delete guards, DM gating."""
import io
import os

import pytest
from PIL import Image

from core.db import db



def _png_bytes(size=64, color=(120, 90, 60)):
    img = Image.new('RGB', (size, size), color)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return buf


@pytest.fixture()
def tex_app(tmp_path, monkeypatch, legacy_app):
    from models.user import tblUsers
    import routers.textures as tex_mod
    # uploads land in a temp dir, not the repo
    monkeypatch.setattr(tex_mod, 'UPLOAD_FOLDER', str(tmp_path))
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    player = tblUsers(username='pl', display_name='PL', password_hash='x',
                      role='player', active=1, created_at='2026-01-01 00:00:00')
    db.session.add_all([dm, player])
    db.session.commit()
    return legacy_app, dm, player


class TestManifest:
    def test_builtin_manifest_served_to_players(self, tex_app):
        a, dm, player = tex_app
        with a.test_client(user=player) as c:
            d = c.get('/ttrpg/textures/manifest').get_json()
        assert d['ok']
        names = {t['name'] for t in d['textures']}
        # the repo starter set is present with categories and urls
        assert 'flagstone' in names and 'oak_planks' in names
        fl = next(t for t in d['textures'] if t['name'] == 'flagstone')
        assert fl['source'] == 'builtin' and fl['tile_ft'] > 0
        assert fl['url'].startswith('/static/textures/builtin/')

    def test_upload_appears_in_manifest(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={'name': 'My Moss', 'category': 'stone', 'tile_ft': '8'}, files={'image': ('moss.png', _png_bytes(), 'image/png')})
            assert r.get_json()['ok'], r.get_json()
            assert r.get_json()['name'] == 'my_moss'   # slugified
            d = c.get('/ttrpg/textures/manifest').get_json()
        mine = next(t for t in d['textures'] if t['name'] == 'my_moss')
        assert mine['source'] == 'upload' and mine['tile_ft'] == 8.0


class TestUploadValidation:
    def test_bad_slug_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'BAD!SLUG'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
        assert r.status_code == 400

    def test_builtin_name_collision_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'flagstone'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
        assert r.status_code == 400
        assert 'already exists' in r.get_json()['error']

    def test_duplicate_upload_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'dupe'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'dupe'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
        assert r.status_code == 400

    def test_downscaled_to_cap(self, tex_app, tmp_path):
        import routers.textures as tex_mod
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'big'}, files={'image': ('big.png', _png_bytes(2048), 'image/png')})
            assert r.get_json()['ok']
        from models.ttrpg import tblTextures
        row = tblTextures.query.filter_by(name='big').first()
        path = os.path.join(tex_mod.UPLOAD_FOLDER, row.filename)
        with Image.open(path) as im:
            assert max(im.size) <= tex_mod.MAX_TEXTURE_DIM

    def test_paste_endpoint(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/paste', data={
                'name': 'pasted', 'category': 'wood', 'source': 'ai',
                'ext': 'png'}, files={'image': ('blob', _png_bytes(), 'image/png')})
            assert r.get_json()['ok']
            d = c.get('/ttrpg/textures/manifest').get_json()
        mine = next(t for t in d['textures'] if t['name'] == 'pasted')
        assert mine['source'] == 'ai'


class TestDelete:
    def test_delete_own_texture_removes_row_and_file(self, tex_app):
        import routers.textures as tex_mod
        from models.ttrpg import tblTextures
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'doomed'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
            row = tblTextures.query.filter_by(name='doomed').first()
            path = os.path.join(tex_mod.UPLOAD_FOLDER, row.filename)
            assert os.path.exists(path)
            r = c.post('/ttrpg/textures/doomed/delete')
            assert r.get_json()['ok']
        assert not os.path.exists(path)
        assert tblTextures.query.filter_by(name='doomed').first() is None

    def test_builtin_not_deletable(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/flagstone/delete')
        assert r.status_code == 404


class TestGating:
    def test_player_cannot_write(self, tex_app):
        a, _, player = tex_app
        with a.test_client(user=player) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'nope'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
            assert r.status_code == 403   # dm_required is a JSON 403 now
            r2 = c.post('/ttrpg/textures/flagstone/delete')
            assert r2.status_code == 403

    def test_anonymous_cannot_read(self, tex_app):
        a, _, _ = tex_app
        with a.test_client() as c:
            r = c.get('/ttrpg/textures/manifest')
        assert r.status_code in (302, 401)


class TestTexturePaths:
    def test_paths_resolve_builtin_and_uploads(self, tex_app):
        import routers.textures as tex_mod
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'mine', 'tile_ft': '7'}, files={'image': ('x.png', _png_bytes(), 'image/png')})
        paths = tex_mod.texture_paths(['flagstone', 'mine', 'ghost'])
        assert 'ghost' not in paths
        assert paths['flagstone']['path'].endswith('builtin/flagstone.jpg')
        assert os.path.exists(paths['flagstone']['path'])
        assert paths['mine']['tile_ft'] == 7.0
        assert os.path.exists(paths['mine']['path'])

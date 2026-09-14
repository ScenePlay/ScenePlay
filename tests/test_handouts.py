"""PDF handouts: upload validation (magic number, size), listing, rename,
delete (row + file), guarded file serving (DM bearer or signed URL), reader
page data, progress resume point, named page bookmarks, and DM gating.
Ported from the Flask tests onto the legacy_app shim (routers/handouts.py)."""
import io
import os

import pytest

from core.db import db

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


@pytest.fixture()
def ho_app(tmp_path, monkeypatch, legacy_app):
    from models.user import tblUsers
    import routers.handouts as mod
    monkeypatch.setattr(mod, 'UPLOAD_FOLDER', str(tmp_path))
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    pl = tblUsers(username='pl', display_name='PL', password_hash='x',
                  role='player', active=1, created_at='2026-01-01 00:00:00')
    db.session.add_all([dm, pl])
    db.session.commit()
    return legacy_app, dm, pl, tmp_path


def _upload(c, data=PDF, name='Monster Manual.pdf', title=None):
    form = {}
    if title is not None:
        form['title'] = title
    return c.post('/handouts/upload', data=form, files={'pdf': (name, io.BytesIO(data), 'application/pdf')})


class TestUpload:
    def test_pdf_lands_on_disk_with_title_from_filename(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c)
            assert r.status_code == 200, r.get_data(as_text=True)
            h = r.get_json()['handout']
            assert h['title'] == 'Monster Manual'
            assert h['filename'].endswith('.pdf') and len(h['filename']) == 36
            assert (tmp / h['filename']).read_bytes() == PDF
            assert h['page_count'] is None and h['last_page'] == 1

    def test_explicit_title_wins_and_is_trimmed(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='  The   Duke\'s  Letter ').get_json()['handout']
            assert h['title'] == "The Duke's Letter"

    def test_rejects_non_pdf_by_magic_not_extension(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c, data=b'\x89PNG....', name='sneaky.pdf')
            assert r.status_code == 400 and 'not a PDF' in r.get_json()['error']
            r = _upload(c, data=b'', name='empty.pdf')
            assert r.status_code == 400
            r = c.post('/handouts/upload', data={'title': 'x'})
            assert r.status_code == 400
        assert not [f for f in os.listdir(tmp) if f.endswith('.pdf')]

    def test_rejects_oversize(self, ho_app, monkeypatch):
        import routers.handouts as mod
        monkeypatch.setattr(mod, 'MAX_PDF_BYTES', 10)
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c)
            assert r.status_code == 400 and 'larger than' in r.get_json()['error']

    def test_upload_returns_json_for_the_spa(self, ho_app):
        """The old form POST redirected to the list; the SPA gets {ok, handout, message}."""
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            r = c.post('/handouts/upload', files={'pdf': ('x.pdf', io.BytesIO(PDF), 'application/pdf')})
            j = r.get_json()
            assert r.status_code == 200 and j['ok'] and j['handout']['title'] == 'x' and 'message' in j
            lst = c.get('/api/v1/handouts').get_json()
            assert [h['title'] for h in lst['handouts']] == ['x'] and lst['max_mb'] == 300
            assert lst['handouts'][0]['file_url_dl'].startswith(f"/handouts/{j['handout']['id']}/file?dl=1&exp=")


class TestManage:
    def test_file_served_inline_and_as_download(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c, title='PHB').get_json()['handout']['id']
            r = c.get(f'/handouts/{hid}/file')
            assert r.status_code == 200 and r.headers['content-type'].startswith('application/pdf')
            assert r.get_data() == PDF and 'attachment' not in (r.headers.get('Content-Disposition') or '')
            r = c.get(f'/handouts/{hid}/file?dl=1')
            assert 'attachment' in r.headers['Content-Disposition'] and 'PHB.pdf' in r.headers['Content-Disposition']
            assert c.get('/handouts/999/file').status_code == 404

    def test_file_served_on_signed_url_without_a_token(self, ho_app, client):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c, title='PHB').get_json()['handout']['id']
            page = c.get(f'/api/v1/handouts/{hid}').get_json()
        url = page['file_url']
        assert url.startswith(f'/handouts/{hid}/file?exp=') and '&sig=' in url
        r = client.get(url)                       # no Authorization header at all (pdf.js)
        assert r.status_code == 200 and r.content == PDF
        assert client.get(f'/handouts/{hid}/file').status_code in (401, 403)   # no token, no signature
        assert client.get(url.replace('&sig=', '&sig=0')).status_code == 403

    def test_reader_page_and_missing_file(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='PHB').get_json()['handout']
            r = c.get(f"/api/v1/handouts/{h['id']}")
            assert r.status_code == 200
            d = r.get_json()
            assert d['file_url'].startswith(f"/handouts/{h['id']}/file")
            assert d['progress_url'] == f"/handouts/{h['id']}/progress"
            assert d['bookmarks_url'] == f"/handouts/{h['id']}/bookmarks"
            assert d['start_page'] == 1 and d['handout']['title'] == 'PHB'
            os.remove(tmp / h['filename'])
            d = c.get(f"/api/v1/handouts/{h['id']}").get_json()
            assert d['redirect'] == '/handouts' and 'missing on disk' in d['message']
            assert c.get(f"/handouts/{h['id']}/file").status_code == 404
            assert c.get('/api/v1/handouts/999').status_code == 404

    def test_progress_bookmark_and_clamp(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
            r = c.post(f'/handouts/{hid}/progress', json={'page_count': 320, 'page': 41})
            assert r.get_json() == {'ok': True, 'last_page': 41, 'page_count': 320}
            r = c.post(f'/handouts/{hid}/progress', json={'page': 999})
            assert r.get_json()['last_page'] == 320
            r = c.post(f'/handouts/{hid}/progress', json={'page': 'junk', 'page_count': -4})
            assert r.get_json() == {'ok': True, 'last_page': 320, 'page_count': 320}
            assert c.get(f'/api/v1/handouts/{hid}').get_json()['start_page'] == 320
            assert c.post('/handouts/999/progress', json={'page': 1}).status_code == 404

    def test_rename_delete_and_listing(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='Old').get_json()['handout']
            r = c.post(f"/handouts/{h['id']}/rename", json={'title': ' New  Name '})
            assert r.get_json() == {'ok': True, 'title': 'New Name'}
            r = c.post(f"/handouts/{h['id']}/rename", json={'title': '   '})
            assert r.get_json()['title'] == 'New Name'         # blank keeps the old title
            r = c.post(f"/handouts/{h['id']}/delete")
            assert r.get_json() == {'ok': True}
            assert not (tmp / h['filename']).exists()
            assert c.post(f"/handouts/{h['id']}/delete").status_code == 404


class TestBookmarks:
    def test_add_list_rename_delete(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c, title='PHB').get_json()['handout']['id']
            c.post(f'/handouts/{hid}/progress', json={'page_count': 320})
            r = c.post(f'/handouts/{hid}/bookmarks', json={'page': 41})
            j = r.get_json()
            assert r.status_code == 200 and j['ok'] and j['created']
            assert j['bookmark']['page'] == 41 and j['bookmark']['label'] == 'Page 41'
            r = c.post(f'/handouts/{hid}/bookmarks', json={'page': 7, 'label': '  Combat   rules '})
            assert r.get_json()['bookmark']['label'] == 'Combat rules'
            # page-ordered listing
            r = c.get(f'/handouts/{hid}/bookmarks')
            assert [(b['page'], b['label']) for b in r.get_json()['bookmarks']] == [(7, 'Combat rules'), (41, 'Page 41')]
            bid = r.get_json()['bookmarks'][1]['id']
            r = c.post(f'/handouts/{hid}/bookmarks/{bid}/rename', json={'label': 'Spellcasting'})
            assert r.get_json()['bookmark'] == {'id': bid, 'page': 41, 'label': 'Spellcasting',
                                                'created_at': r.get_json()['bookmark']['created_at']}
            r = c.post(f'/handouts/{hid}/bookmarks/{bid}/rename', json={'label': '   '})
            assert r.get_json()['bookmark']['label'] == 'Spellcasting'      # blank keeps the label
            r = c.post(f'/handouts/{hid}/bookmarks/{bid}/delete')
            assert [b['page'] for b in r.get_json()['bookmarks']] == [7]
            assert c.post(f'/handouts/{hid}/bookmarks/{bid}/delete').status_code == 404
            assert c.post(f'/handouts/{hid}/bookmarks/{bid}/rename', json={'label': 'x'}).status_code == 404

    def test_one_per_page_upserts_and_page_is_clamped(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
            c.post(f'/handouts/{hid}/progress', json={'page_count': 50})
            first = c.post(f'/handouts/{hid}/bookmarks', json={'page': 5}).get_json()
            again = c.post(f'/handouts/{hid}/bookmarks', json={'page': 5, 'label': 'Maps'}).get_json()
            assert again['created'] is False
            assert again['bookmark']['id'] == first['bookmark']['id'] and again['bookmark']['label'] == 'Maps'
            # sending no label on an existing page keeps the current label
            same = c.post(f'/handouts/{hid}/bookmarks', json={'page': 5}).get_json()
            assert same['bookmark']['label'] == 'Maps' and len(same['bookmarks']) == 1
            # past the known count clamps to the last page; junk is rejected
            r = c.post(f'/handouts/{hid}/bookmarks', json={'page': 999})
            assert r.get_json()['bookmark']['page'] == 50
            for bad in ({'page': 0}, {'page': 'nope'}, {}):
                assert c.post(f'/handouts/{hid}/bookmarks', json=bad).status_code == 400
            assert c.post('/handouts/999/bookmarks', json={'page': 1}).status_code == 404
            assert c.get('/handouts/999/bookmarks').status_code == 404

    def test_bookmark_of_other_handout_is_not_reachable(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            h1 = _upload(c, name='a.pdf').get_json()['handout']['id']
            h2 = _upload(c, name='b.pdf').get_json()['handout']['id']
            bid = c.post(f'/handouts/{h1}/bookmarks', json={'page': 3}).get_json()['bookmark']['id']
            assert c.post(f'/handouts/{h2}/bookmarks/{bid}/delete').status_code == 404
            assert c.post(f'/handouts/{h2}/bookmarks/{bid}/rename', json={'label': 'x'}).status_code == 404
            assert len(c.get(f'/handouts/{h1}/bookmarks').get_json()['bookmarks']) == 1

    def test_reader_and_list_carry_bookmarks_and_page_param(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c, title='PHB').get_json()['handout']['id']
            c.post(f'/handouts/{hid}/progress', json={'page_count': 100, 'page': 60})
            c.post(f'/handouts/{hid}/bookmarks', json={'page': 12, 'label': 'Races <b>'})
            d = c.get(f'/api/v1/handouts/{hid}').get_json()
            assert d['start_page'] == 60                                   # resume point by default
            assert d['handout']['bookmarks'] == [{'id': d['handout']['bookmarks'][0]['id'], 'page': 12, 'label': 'Races <b>',
                                                  'created_at': d['handout']['bookmarks'][0]['created_at']}]
            assert c.get(f'/api/v1/handouts/{hid}?page=12').get_json()['start_page'] == 12   # a bookmark link opens there
            assert c.get(f'/api/v1/handouts/{hid}?page=500').get_json()['start_page'] == 100
            assert c.get(f'/api/v1/handouts/{hid}?page=junk').get_json()['start_page'] == 60
            lst = c.get('/api/v1/handouts').get_json()['handouts']
            assert lst[0]['bookmarks'][0]['page'] == 12 and lst[0]['bookmarks'][0]['label'] == 'Races <b>'

    def test_deleting_handout_removes_its_bookmarks(self, ho_app):
        from models.ttrpg import tblHandoutBookmarks
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
            c.post(f'/handouts/{hid}/bookmarks', json={'page': 2})
            c.post(f'/handouts/{hid}/bookmarks', json={'page': 9})
            assert tblHandoutBookmarks.query.count() == 2
            assert c.post(f'/handouts/{hid}/delete').get_json() == {'ok': True}
            assert tblHandoutBookmarks.query.count() == 0


class TestGating:
    def test_player_and_anonymous_are_bounced(self, ho_app):
        a, dm, pl, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
        with a.test_client(user=pl) as c:
            for path in (f'/handouts/{hid}/file', f'/api/v1/handouts/{hid}', '/api/v1/handouts'):
                r = c.get(path)
                assert r.status_code == 403 and r.get_json()['code'] == 'dm_required', path
            assert c.post(f'/handouts/{hid}/delete').status_code == 403
            assert c.get(f'/handouts/{hid}/bookmarks').status_code == 403
            assert c.post(f'/handouts/{hid}/bookmarks', json={'page': 1}).status_code == 403
            assert _upload(c).status_code == 403
        with a.test_client() as c:
            assert c.get(f'/handouts/{hid}/file').status_code in (401, 403)  # require_dm_or_signed: no token, no signature
            assert c.get('/api/v1/handouts').status_code == 401

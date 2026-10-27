"""ThumbnailStore: download → Pillow-shrink → atomic save, plus the worker's
one-per-poll backfill sweep. Network is stubbed — a fake requests.get serves
Pillow-generated images."""
import os
import sqlite3
from io import BytesIO

import pytest
from PIL import Image

import media.thumbs as thumbs
from media.thumbs import ThumbnailStore


def png_bytes(width, height, color=(200, 30, 30)):
    buf = BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'PNG')
    return buf.getvalue()


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status = status

    def raise_for_status(self):
        if self.status != 200:
            # Same shape as a real requests failure: the store reads
            # err.response.status_code to tell "gone" from "try later".
            err = thumbs.requests.HTTPError(f'HTTP {self.status}')
            err.response = self
            raise err

    @property
    def status_code(self):
        return self.status


class FakeOffline:
    """requests.get stand-in for a box with no network."""
    def __init__(self, url):
        raise thumbs.requests.ConnectionError('no route to host')


@pytest.fixture()
def store(tmp_path, monkeypatch):
    st = ThumbnailStore(directory=str(tmp_path / 'thumbs'), max_width=320)
    st._responses = {}
    monkeypatch.setattr(thumbs.requests, 'get',
                        lambda url, timeout=0: st._responses[url])
    return st


class TestStore:
    def test_downscales_wide_image(self, store):
        store._responses['https://x/big.png'] = FakeResponse(png_bytes(1280, 720))
        assert store.cache('music', 7, 'https://x/big.png') is True
        img = Image.open(store.path('music', 7))
        assert img.format == 'JPEG'
        assert img.size == (320, 180)          # aspect preserved
        assert os.path.getsize(store.path('music', 7)) < 20_000

    def test_small_image_not_upscaled(self, store):
        store._responses['https://x/small.png'] = FakeResponse(png_bytes(120, 90))
        store.cache('video', 3, 'https://x/small.png')
        assert Image.open(store.path('video', 3)).size == (120, 90)

    def test_url_only_when_cached(self, store):
        assert store.url('music', 7) is None
        store._responses['https://x/a.png'] = FakeResponse(png_bytes(100, 100))
        store.cache('music', 7, 'https://x/a.png')
        assert store.url('music', 7) == '/static/thumbs/music_7.jpg'

    def test_failures_return_false_never_raise(self, store):
        assert store.cache('music', 1, None) is False
        assert store.cache('music', 1, '') is False
        store._responses['https://x/404.png'] = FakeResponse(b'', status=404)
        assert store.cache('music', 1, 'https://x/404.png') is False
        store._responses['https://x/junk.png'] = FakeResponse(b'not an image')
        assert store.cache('music', 1, 'https://x/junk.png') is False
        assert not store.exists('music', 1)    # no partial file left behind

    def test_cache_result_tells_gone_from_retry(self, store, monkeypatch):
        """A definite 404/410 means the picture no longer exists at YouTube
        (the video was removed): 'gone'. Anything else — 5xx, bad image,
        offline — is 'retry' so an offline Pi never discards a good URL."""
        store._responses['https://x/404.png'] = FakeResponse(b'', status=404)
        store._responses['https://x/410.png'] = FakeResponse(b'', status=410)
        store._responses['https://x/500.png'] = FakeResponse(b'', status=500)
        store._responses['https://x/junk.png'] = FakeResponse(b'not an image')
        store._responses['https://x/ok.png'] = FakeResponse(png_bytes(50, 50))
        assert store.cache_result('music', 1, 'https://x/404.png') == 'gone'
        assert store.cache_result('music', 1, 'https://x/410.png') == 'gone'
        assert store.cache_result('music', 1, 'https://x/500.png') == 'retry'
        assert store.cache_result('music', 1, 'https://x/junk.png') == 'retry'
        assert store.cache_result('music', 1, '') == 'retry'
        assert store.cache_result('music', 1, 'https://x/ok.png') == 'ok'
        monkeypatch.setattr(thumbs.requests, 'get', lambda url, timeout=0: FakeOffline(url))
        assert store.cache_result('music', 2, 'https://x/ok.png') == 'retry'


class TestBackfill:
    @pytest.fixture()
    def env(self, tmp_path, monkeypatch, store):
        import sql
        import media.meta_que as meta_que
        db = str(tmp_path / 'live.db')
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, "
                     "media_type TEXT, media_id INT, thumbnail TEXT)")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('music', 1, 'https://x/1.png')")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('music', 2, 'https://x/2.png')")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('video', 3, '')")   # no URL -> ignored
        conn.commit()
        conn.close()
        monkeypatch.setattr(sql, 'database', db)
        monkeypatch.setattr(meta_que, 'thumb_store', store)
        monkeypatch.setattr(meta_que, '_thumb_next_scan', 0.0)
        monkeypatch.setattr(meta_que, '_thumb_failed', set())
        store._responses['https://x/1.png'] = FakeResponse(png_bytes(640, 480))
        store._responses['https://x/2.png'] = FakeResponse(png_bytes(640, 480))
        return store

    def test_one_per_call_until_clean(self, env):
        from media.meta_que import backfill_one_thumbnail
        assert backfill_one_thumbnail() is True    # music/1
        assert env.exists('music', 1) and not env.exists('music', 2)
        assert backfill_one_thumbnail() is True    # music/2
        assert env.exists('music', 2)
        assert backfill_one_thumbnail() is False   # clean -> sweep goes dormant
        assert backfill_one_thumbnail() is False   # ...and stays dormant (rescan timer)

    def test_failed_url_not_retried(self, env):
        import media.meta_que as meta_que
        env._responses['https://x/1.png'] = FakeResponse(b'', status=500)
        assert meta_que.backfill_one_thumbnail() is True    # attempted music/1, failed
        assert not env.exists('music', 1)
        assert meta_que.backfill_one_thumbnail() is True    # moves ON to music/2
        assert env.exists('music', 2)
        assert ('music', 1) in meta_que._thumb_failed

    def _url_in_db(self, media_id):
        import sql
        conn = sqlite3.connect(sql.database)
        try:
            return conn.execute("SELECT thumbnail FROM tblMediaMetadata WHERE media_type='music' "
                                "AND media_id=?", (media_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_gone_url_is_cleared_so_no_boot_ever_retries_it(self, env):
        """The data that drove the boot-time '[thumbs] cache failed ... 404'
        spam: a thumbnail URL for a video YouTube has removed. A definite 404
        blanks the column, so the sweep's query (thumbnail <> '') never picks
        the row again — not this run, not after a restart."""
        import media.meta_que as meta_que
        env._responses['https://x/1.png'] = FakeResponse(b'', status=404)
        assert meta_que.backfill_one_thumbnail() is True    # attempted music/1: gone
        assert self._url_in_db(1) == ''
        assert ('music', 1) not in meta_que._thumb_failed, 'nothing to remember — the DB says so now'
        assert meta_que.backfill_one_thumbnail() is True    # music/2 as usual
        meta_que._thumb_failed.clear()                       # "restart"
        meta_que._thumb_next_scan = 0.0
        assert meta_que.backfill_one_thumbnail() is False   # nothing left to try

    def test_retryable_failure_keeps_the_url(self, env, monkeypatch):
        """5xx or no network must NOT blank the URL: the picture may well exist."""
        import media.meta_que as meta_que
        env._responses['https://x/1.png'] = FakeResponse(b'', status=500)
        assert meta_que.backfill_one_thumbnail() is True
        assert self._url_in_db(1) == 'https://x/1.png'
        monkeypatch.setattr(thumbs.requests, 'get', lambda url, timeout=0: FakeOffline(url))
        assert meta_que.backfill_one_thumbnail() is True    # music/2 offline
        assert self._url_in_db(2) == 'https://x/2.png'
        assert ('music', 2) in meta_que._thumb_failed

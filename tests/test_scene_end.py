"""Lights off when a scene's media finishes.

scene_media_finished() is the rule; scene_end.notify_if_scene_ended() is the
worker-side trigger; routers.public.lights_off() is the fan-out the endpoint
runs. The rule is strict on purpose — see the cases below.
"""
import sqlite3

import pytest

import sql
import media.scene_end as scene_end


def _db(tmp_path):
    path = str(tmp_path / 'end.db')
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE tblAppSettings (id INTEGER PRIMARY KEY, name TEXT, value TEXT, typevalue TEXT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT)")
    c.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT)")
    for name, value in (('CurrentScene', '3'), ('playsongswitch', '0'), ('playvideoswitch', '0'),
                        ('currentsong', '0'), ('currentvideo', '0')):
        c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES (?, ?, 'int')", (name, value))
    c.execute("INSERT INTO tblMusicScene(scene_ID, song_ID) VALUES (3, 11)")
    c.commit()
    c.close()
    return path


def _set(path, name, value):
    c = sqlite3.connect(path)
    c.execute("UPDATE tblAppSettings SET value=? WHERE name=?", (str(value), name))
    c.commit()
    c.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setattr(sql, 'database', path)
    return path


class TestRule:
    def test_ended_when_scene_had_media_and_all_idle(self, db):
        assert sql.scene_media_finished() is True

    def test_not_ended_while_a_flag_is_on(self, db):
        _set(db, 'playvideoswitch', 1)          # other player still has work
        assert sql.scene_media_finished() is False
        _set(db, 'playvideoswitch', 0)
        _set(db, 'playsongswitch', 1)
        assert sql.scene_media_finished() is False

    def test_not_ended_while_something_is_marked_playing(self, db):
        _set(db, 'currentvideo', 42)
        assert sql.scene_media_finished() is False

    def test_lighting_only_scene_never_ends(self, db):
        c = sqlite3.connect(db)
        c.execute("DELETE FROM tblMusicScene")
        c.commit()
        c.close()
        assert sql.scene_media_finished() is False

    def test_video_only_scene_counts_as_media(self, db):
        c = sqlite3.connect(db)
        c.execute("DELETE FROM tblMusicScene")
        c.execute("INSERT INTO tblVideoScene(scene_ID, video_ID) VALUES (3, 7)")
        c.commit()
        c.close()
        assert sql.scene_media_finished() is True

    def test_no_scene_or_kill_queue_scene(self, db):
        _set(db, 'CurrentScene', 0)
        assert sql.scene_media_finished() is False
        _set(db, 'CurrentScene', -1)
        assert sql.scene_media_finished() is False

    def test_toggle_off_disables(self, db):
        sql.appsettingSet(sql.LIGHTS_OFF_ON_SCENE_END, '0')
        assert sql.lights_off_on_scene_end_enabled() is False
        assert sql.scene_media_finished() is False
        sql.appsettingSet(sql.LIGHTS_OFF_ON_SCENE_END, '1')
        assert sql.scene_media_finished() is True

    def test_default_is_on(self, db):
        assert sql.lights_off_on_scene_end_enabled() is True


class TestNotify:
    def test_posts_loopback_when_ended(self, db):
        calls = []
        assert scene_end.notify_if_scene_ended(post=lambda url, timeout: calls.append((url, timeout))) is True
        assert calls == [(scene_end.LIGHTS_OFF_URL, scene_end.TIMEOUT)]
        assert '127.0.0.1:8086/api/lights-off' in scene_end.LIGHTS_OFF_URL

    def test_silent_when_not_ended(self, db):
        _set(db, 'playsongswitch', 1)
        calls = []
        assert scene_end.notify_if_scene_ended(post=lambda *a, **k: calls.append(a)) is False
        assert calls == []

    def test_request_failure_never_raises(self, db):
        def boom(*a, **k):
            raise ConnectionError('web process down')
        assert scene_end.notify_if_scene_ended(post=boom) is False

    def test_rule_failure_never_raises(self, monkeypatch):
        monkeypatch.setattr(sql, 'database', '/nonexistent/dir/x.db')
        assert scene_end.notify_if_scene_ended(post=lambda *a, **k: None) is False


class TestLightsOff:
    def test_fans_out_to_every_output(self, db, monkeypatch):
        import routers.public as m
        sent = {}
        monkeypatch.setattr(m, 'dispatch_led', lambda payload: sent.setdefault('led', payload))
        monkeypatch.setattr(m, 'wled_Off', lambda: sent.setdefault('wled', True))
        monkeypatch.setattr(m.relay_broadcaster, 'broadcast_wled', lambda rows: sent.setdefault('relay_wled', rows))
        m.lights_off()
        import lighting.led_patterns as led_patterns
        assert sent == {'led': led_patterns.OFF_PAYLOAD, 'wled': True, 'relay_wled': []}
        assert m._lights_dark() is True     # a re-click of the scene must re-push


class TestReactivateAfterLightsOff:
    """Re-clicking the ACTIVE scene normally skips the device pushes (the
    lights already show it). Once lights_off() has run — scene media ended,
    or the Lights-off button — that assumption is false and the re-click
    must push the scene's lighting again."""

    @pytest.fixture
    def scene(self, app, monkeypatch):
        import json
        import routers.public as m
        conn = sqlite3.connect(sql.database)
        conn.execute("INSERT INTO tblScenePattern(scene_ID, patternType, params, orderBy) VALUES (7, 'solid', ?, 1)",
                     (json.dumps({'color': [255, 0, 0]}),))
        conn.commit()
        conn.close()
        sent = []
        monkeypatch.setattr(m, 'dispatch_led', lambda payload, local=True: sent.append(('led', payload)))
        monkeypatch.setattr(m, 'wled_Off', lambda: sent.append(('wled', 'off')))
        monkeypatch.setattr(m, 'setWledEffect', lambda *a: sent.append(('wled', a)))
        monkeypatch.setattr(m.relay_broadcaster, 'broadcast_wled', lambda rows: sent.append(('relay_wled', rows)))
        monkeypatch.setattr(m, 'getWledPatternBySceneID', lambda sid: [])
        for name in ('queue_kill', 'queue_next', 'queueVideo_next'):
            monkeypatch.setattr(m, name, lambda: None)
        monkeypatch.setattr(m, '_players_alive', lambda: False)
        monkeypatch.setattr(m.time, 'sleep', lambda s: None)
        return m, sent

    @staticmethod
    def _led_payloads(sent):
        import json
        return [json.loads(p)['patterns'] for kind, p in sent if kind == 'led']

    def test_reclick_pushes_lights_again_after_lights_off(self, scene):
        m, sent = scene
        m._activate_scene('7')
        assert self._led_payloads(sent)[0][0]['color'] == [255, 0, 0]
        sent.clear()
        m.lights_off()
        assert self._led_payloads(sent) == [[{'type': 'solid', 'color': [0, 0, 0]}]]
        sent.clear()
        m._activate_scene('7')          # same scene, lights are dark
        assert self._led_payloads(sent)[0][0]['color'] == [255, 0, 0]
        assert ('relay_wled', []) in sent and ('wled', 'off') in sent

    def test_reclick_with_lights_showing_skips_pushes(self, scene):
        m, sent = scene
        m._activate_scene('7')
        sent.clear()
        m._activate_scene('7')          # plain re-click: lights already show it
        assert sent == []

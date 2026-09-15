"""Studio Mode helpers on the obs-websocket client: preview / program, the
transition trigger, record chapters and screenshots. `request` is stubbed so
no socket is involved; the cache and the request payloads are what matter."""
import base64

import pytest

import integrations.obs_ws as ow


@pytest.fixture()
def ws(monkeypatch):
    sent = []
    replies = {}

    def fake_request(rtype, data=None, timeout=3):
        sent.append((rtype, data or {}))
        r = replies.get(rtype)
        if isinstance(r, Exception):
            raise r
        return r or {}

    monkeypatch.setattr(ow, '_state', 'connected')
    monkeypatch.setattr(ow, 'request', fake_request)
    monkeypatch.setattr(ow, '_record_error', lambda *a: None)
    monkeypatch.setattr(ow, '_clear_error', lambda *a: None)
    monkeypatch.setattr(ow, '_cache', ow._blank_cache())
    return {'sent': sent, 'replies': replies}


def test_blank_cache_has_preview_and_last_switch():
    c = ow._blank_cache()
    assert c['preview_scene'] == '' and c['last_switch'] is None


def test_set_studio_mode_sends_and_caches(ws):
    ow.set_studio_mode(True)
    assert ws['sent'] == [('SetStudioModeEnabled', {'studioModeEnabled': True})]
    assert ow.current_state()['studio_mode'] is True
    ow.set_studio_mode(False)
    assert ow.current_state()['studio_mode'] is False


def test_set_preview_scene_caches_and_event_overrides(ws):
    ow.set_preview_scene('Player - Carl')
    assert ws['sent'] == [('SetCurrentPreviewScene', {'sceneName': 'Player - Carl'})]
    assert ow.preview_scene() == 'Player - Carl'
    ow._handle_event('CurrentPreviewSceneChanged', {'sceneName': 'ScenePlay Map'})
    assert ow.preview_scene() == 'ScenePlay Map'


def test_set_transition_with_duration(ws):
    ow.set_transition('Fade', 300)
    assert ws['sent'] == [('SetCurrentSceneTransition', {'transitionName': 'Fade'}),
                          ('SetCurrentSceneTransitionDuration', {'transitionDuration': 300})]


def test_set_transition_tolerates_fixed_transition_rejecting_duration(ws):
    ws['replies']['SetCurrentSceneTransitionDuration'] = ow.ObsRejected(600, 'fixed')
    ow.set_transition('Cut', 300)          # must not raise
    assert ws['sent'][0] == ('SetCurrentSceneTransition', {'transitionName': 'Cut'})


def test_trigger_transition_records_producer_switch(ws):
    ow.set_preview_scene('Player - Mira')
    ow.trigger_transition()
    assert ('TriggerStudioModeTransition', {}) in ws['sent']
    last = ow.current_state()['last_switch']
    assert last['by'] == 'producer' and last['scene'] == 'Player - Mira' and last['at'] > 0


def test_switch_scene_records_who_switched(ws):
    ow.switch_scene('ScenePlay Party')
    assert ow.current_state()['last_switch']['by'] == 'auto'
    ow.switch_scene('ScenePlay Map', by='broadcast')
    assert ow.current_state()['last_switch'] == {
        'by': 'broadcast', 'scene': 'ScenePlay Map',
        'at': ow.current_state()['last_switch']['at']}


def test_record_chapter(ws):
    ow.record_chapter('Act 2 begins')
    assert ws['sent'] == [('CreateRecordChapter', {'chapterName': 'Act 2 begins'})]


def test_screenshot_returns_decoded_bytes(ws):
    raw = b'\xff\xd8\xff\xe0jpegbytes'
    ws['replies']['GetSourceScreenshot'] = {
        'imageData': 'data:image/jpg;base64,' + base64.b64encode(raw).decode()}
    out = ow.screenshot('ScenePlay Map', width=320)
    assert out == raw
    assert ws['sent'] == [('GetSourceScreenshot', {
        'sourceName': 'ScenePlay Map', 'imageFormat': 'jpg',
        'imageWidth': 320, 'imageCompressionQuality': 60})]


def test_screenshot_without_data_is_empty(ws):
    ws['replies']['GetSourceScreenshot'] = {}
    assert ow.screenshot('x') == b''


def test_meter_events_reidentify_and_flag(ws, monkeypatch):
    frames = []
    monkeypatch.setattr(ow, '_send', lambda f: frames.append(f))
    monkeypatch.setattr(ow, '_meter_events', False)
    ow.set_meter_events(True)
    assert frames == [{'op': 3, 'd': {'eventSubscriptions': ow.EVENT_SUBS | ow.METER_EVENT_FLAG}}]
    assert ow._event_subs() == ow.EVENT_SUBS | ow.METER_EVENT_FLAG
    ow.set_meter_events(False)
    assert frames[-1] == {'op': 3, 'd': {'eventSubscriptions': ow.EVENT_SUBS}}
    assert ow._event_subs() == ow.EVENT_SUBS


def test_meter_events_when_disconnected_only_remember(ws, monkeypatch):
    frames = []
    monkeypatch.setattr(ow, '_send', lambda f: frames.append(f))
    monkeypatch.setattr(ow, '_state', 'reconnecting')
    ow.set_meter_events(True)
    assert frames == [] and ow._event_subs() & ow.METER_EVENT_FLAG


def test_input_volume_meters_event_fills_levels(ws, monkeypatch):
    monkeypatch.setattr(ow, '_levels', {})
    ow._handle_event('InputVolumeMeters', {'inputs': [
        {'inputName': 'Player - Carl Cam', 'inputLevelsMul': [[0.1, 0.5, 0.6], [0.1, 0.4, 0.6]]},
        {'inputName': 'ScenePlay Music', 'inputLevelsMul': [[0.2, 0.9, 0.9]]},
        {'inputName': 'silent', 'inputLevelsMul': []},
    ]})
    lv, at = ow.levels()
    assert lv == {'Player - Carl Cam': [0.5, 0.4], 'ScenePlay Music': [0.9], 'silent': []}
    assert at > 0


def test_connected_hooks_are_registered_once_and_isolated(ws, monkeypatch):
    """One hook that raises must not stop the others (they run on the session's
    reconnect path, where an exception would take the socket down)."""
    monkeypatch.setattr(ow, '_connected_hooks', [])
    ran = []

    def boom():
        raise RuntimeError('hook exploded')

    ow.add_connected_hook(boom)
    ow.add_connected_hook(lambda: ran.append('ok'))
    ow.add_connected_hook(boom)                     # idempotent per function
    assert len(ow._connected_hooks) == 2
    ow._run_connected_hooks()                       # must not raise
    assert ran == ['ok']


def test_malformed_meter_frame_leaves_levels_alone(ws, monkeypatch):
    """20 frames a second arrive on the reader thread: a junk one may cost its
    own levels, never the session."""
    monkeypatch.setattr(ow, '_levels', {})
    ow._handle_event('InputVolumeMeters', {'inputs': [
        {'inputName': 'ScenePlay Music', 'inputLevelsMul': [[0.2, 0.9, 0.9]]}]})
    good, _at = ow.levels()
    assert good == {'ScenePlay Music': [0.9]}
    ow._handle_event('InputVolumeMeters', {'inputs': [
        {'inputName': 'Bad', 'inputLevelsMul': [['x', 'y']]}]})
    assert ow.levels()[0] == good, 'unparsable peaks: keep the last good frame'
    ow._handle_event('InputVolumeMeters', {'inputs': 'nonsense'})
    assert ow.levels()[0] == good
    # A short channel entry is not junk — it reads as silence, as before.
    ow._handle_event('InputVolumeMeters', {'inputs': [
        {'inputName': 'Quiet', 'inputLevelsMul': [['x']]}]})
    assert ow.levels()[0] == {'Quiet': [0.0]}


def test_ensure_item_adds_an_existing_input_once(ws):
    ws['replies']['GetSceneItemList'] = {'sceneItems': [{'sourceName': 'Player - Carl Cam', 'sceneItemId': 7}]}
    assert ow.ensure_item('Player - Carl', 'Player - Carl Cam') == 7
    assert not any(r == 'CreateSceneItem' for r, _ in ws['sent'])
    ws['replies']['GetSceneItemList'] = {'sceneItems': []}
    ws['replies']['CreateSceneItem'] = {'sceneItemId': 42}
    assert ow.ensure_item('Player - Carl', 'Player - Carl Overlay') == 42
    assert ('CreateSceneItem', {'sceneName': 'Player - Carl', 'sourceName': 'Player - Carl Overlay', 'sceneItemEnabled': True}) in ws['sent']

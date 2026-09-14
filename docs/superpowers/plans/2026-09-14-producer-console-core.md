# Producer Console (core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A DM-gated `/ttrpg/producer` page where a second person on their own laptop arms and takes OBS shots (Studio Mode), watches snapshot thumbnails, runs the audio strip, fires ScenePlay scenes, keeps clocks and drops recording markers.

**Architecture:** A new thin router `routers/producer.py` sits beside the OBS router and reuses its scene naming, party ordering and cut event; `integrations/obs_ws.py` gains the Studio Mode, preview, transition, chapter, screenshot and meter helpers; a vanilla ES-module view `web/app/views/ttrpg/producer/` renders the console and polls snapshot/level endpoints while listening to the `producer`, `obs`, `queue` and `nowplaying` SSE topics. No new tables.

**Tech Stack:** FastAPI (plain `def` endpoints), obs-websocket v5 over the existing `integrations/obs_ws.py` client, SQLite `tblAppSettings` for the few persisted keys, vanilla ES modules + Bootstrap 5 for the page, pytest with the `legacy_app` client, Playwright smoke via `scripts/spa_smoke.py`.

**Spec:** `docs/superpowers/specs/2026-09-14-producer-console-core-design.md`

## Global Constraints

- Never `git push`. Commit after each task with the message given in the task; the pre-commit hook bumps the PATCH version by itself (do not edit `version.py`/`pyproject.toml`).
- No new tables, columns or Alembic revisions in this phase. Persisted keys live in `tblAppSettings` via `sql.appsettingGet/appsettingSet`, session-scoped with the `:s<session_id>` suffix (empty suffix when no session is active).
- Endpoints are plain `def` (thread pool). `async def` is only for SSE. Every producer endpoint is `Depends(require_dm)`.
- Error envelope: raise `security.deps.ApiError(status, message, code=...)` for request errors; OBS failures return `{"ok": False, "error": "<text>"}` with HTTP 200 like the OBS router does.
- Run tests as `.venv/bin/python -m pytest tests/<file> -q -p no:warnings` from the repo root; lint with `.venv/bin/ruff check .`. `tests/test_web_assets.py` must stay green after any change under `web/`.
- Session-less paths (`/activatescenes/`, `/nextsong`, `/killqueue`, `/set_volume`, `/api/scenes`) are reused as they are; never add auth to them.
- Timestamps are local `'%Y-%m-%d %H:%M:%S'` strings.
- Import style is absolute (`import integrations.obs_ws as obs_ws`, `import routers.obs as obs`).
- The running appliance on this box is the live instance; do not restart it from tests. Manual checks go through `scripts/spa_smoke.py` against a server you start yourself (`SP_PORT=8091 SP_WORKERS=0 SP_INTEGRATIONS=0 .venv/bin/python ws.py` in another terminal).

---

## File map

| File | Responsibility |
|---|---|
| `integrations/obs_ws.py` (modify) | Studio Mode, preview scene, transition, record chapter, screenshot bytes, meter events + `levels()`, `by` tag on `switch_scene`. |
| `routers/producer.py` (create) | Console registry (open / ping / close), Studio Mode lifecycle, auto-cam pause, state document, arm / take / auto / transition, countdown + clock, markers, snapshot and level endpoints. |
| `routers/obs/__init__.py` (modify) | `auto_cam_on()` honours the producer pause; `_cut` tags its switch `by='broadcast'`; Broadcast page data gets `producer_url`. |
| `core/events.py`, `web/app/topics.js` (modify) | `producer` topic. |
| `app.py` (modify) | Register the producer router. |
| `web/app/routes.js` (modify) | `/ttrpg/producer` route. |
| `web/app/views/ttrpg/producer/index.js` (create) | mount/unmount: session open + ping, subscriptions, timers, hotkeys. |
| `web/app/views/ttrpg/producer/template.js` (create) | Markup for the four zones from state. |
| `web/app/views/ttrpg/producer/console.js` (create) | Actions and painters: arm/take/auto, snapshots, levels, audio strip, ScenePlay tiles, clocks, markers. |
| `web/css/views/producer.css` (create) | Console layout (grid), tally borders, meters. |
| `web/app/views/ttrpg/obs_broadcast/template.js` (modify) | "Open producer console" link. |
| `tests/test_obs_ws_studio.py` (create) | obs_ws helper tests. |
| `tests/test_producer_api.py` (create) | Router tests with a stubbed `obs_ws`. |
| `tests/test_events.py` (modify) | `producer` topic accepted. |
| `scripts/spa_smoke.py` (modify) | `/ttrpg/producer` in the default walk. |
| `CLAUDE.md`, `README.md` (modify) | One paragraph each. |

---

### Task 1: obs_ws Studio Mode, preview, transition, chapter and screenshot helpers

**Files:**
- Modify: `integrations/obs_ws.py` (`_blank_cache` ~line 78, `switch_scene` ~line 190, `_handle_event` ~line 1171)
- Test: `tests/test_obs_ws_studio.py`

**Interfaces:**
- Consumes: existing `request(request_type, data=None, timeout=3)`, `_cache`, `_cache_lock`, `current_state()`, `_set_transition_duration(ms, timeout)`, `ObsUnavailable`, `ObsRejected`.
- Produces (all module-level in `integrations.obs_ws`):
  - `set_studio_mode(on: bool, timeout=3) -> None`
  - `preview_scene() -> str` (cached, `''` when none)
  - `set_preview_scene(name: str, timeout=3) -> None`
  - `set_transition(name: str, duration_ms: int | None = None, timeout=3) -> None`
  - `trigger_transition(timeout=3) -> None`
  - `record_chapter(name: str, timeout=3) -> None`
  - `screenshot(source: str, width=320, image_format='jpg', quality=60, timeout=3) -> bytes`
  - `switch_scene(name, transition=None, duration_ms=None, timeout=3, by='auto')` records `current_state()['last_switch'] == {'by', 'scene', 'at'}`
  - cache keys `preview_scene` (str) and `last_switch` (dict or None); event `CurrentPreviewSceneChanged` updates `preview_scene`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_obs_ws_studio.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_obs_ws_studio.py -q -p no:warnings`
Expected: FAIL — `KeyError: 'preview_scene'` and `AttributeError: module 'integrations.obs_ws' has no attribute 'set_studio_mode'`.

- [ ] **Step 3: Add the cache keys**

In `integrations/obs_ws.py`, inside `_blank_cache()` add two entries after `'studio_mode': False,`:

```python
        'preview_scene': '',
        'last_switch': None,     # {'by': 'producer'|'broadcast'|'auto', 'scene', 'at'}
```

- [ ] **Step 4: Tag `switch_scene` and add the helpers**

Replace the whole `switch_scene` function with:

```python
def switch_scene(name, transition=None, duration_ms=None, timeout=3, by='auto'):
    """Cut OBS's PROGRAM scene directly (legal in Studio Mode too). `by` tags
    who moved the shot for the producer console: 'broadcast' (Broadcast page),
    'producer', or 'auto' (auto-cam, scene link, auto-return, group cuts)."""
    if transition:
        set_transition(transition, duration_ms, timeout=timeout)
    request('SetCurrentProgramScene', {'sceneName': name}, timeout=timeout)
    # Optimistic; CurrentProgramSceneChanged confirms a beat later.
    with _cache_lock:
        _cache['current_scene'] = name
        _cache['last_switch'] = {'by': by, 'scene': name, 'at': time.time()}
    _clear_error()
    return name


def set_transition(name, duration_ms=None, timeout=3):
    """Select the transition (and duration) the next cut / Take will use.
    Fixed transitions (Cut) reject a duration — never fatal."""
    try:
        request('SetCurrentSceneTransition', {'transitionName': name}, timeout=timeout)
        if duration_ms:
            _set_transition_duration(int(duration_ms), timeout)
    except ObsRejected as exc:
        log.info('OBS transition setup rejected (%s) — continuing', exc)


# ── Studio Mode (producer console) ──────────────────────────────────────────

def set_studio_mode(on, timeout=3):
    request('SetStudioModeEnabled', {'studioModeEnabled': bool(on)}, timeout=timeout)
    with _cache_lock:
        _cache['studio_mode'] = bool(on)


def preview_scene():
    return current_state().get('preview_scene', '')


def set_preview_scene(name, timeout=3):
    request('SetCurrentPreviewScene', {'sceneName': name}, timeout=timeout)
    with _cache_lock:
        _cache['preview_scene'] = name


def trigger_transition(timeout=3):
    """Take: preview becomes program with the current transition."""
    scene = preview_scene()
    request('TriggerStudioModeTransition', {}, timeout=timeout)
    with _cache_lock:
        _cache['last_switch'] = {'by': 'producer', 'scene': scene, 'at': time.time()}
    _clear_error()


def record_chapter(name, timeout=3):
    """obs-websocket 5.5+: a chapter marker in the running recording."""
    request('CreateRecordChapter', {'chapterName': name}, timeout=timeout)


def screenshot(source, width=320, image_format='jpg', quality=60, timeout=3):
    """One frame of a scene or source as raw image bytes (b'' when OBS sent
    nothing). The producer console's multiview polls this."""
    import base64
    r = request('GetSourceScreenshot',
                {'sourceName': source, 'imageFormat': image_format,
                 'imageWidth': int(width), 'imageCompressionQuality': int(quality)},
                timeout=timeout)
    data = (r or {}).get('imageData', '') or ''
    if ',' in data:
        data = data.split(',', 1)[1]
    try:
        return base64.b64decode(data) if data else b''
    except Exception:
        return b''
```

Check the module already imports `time` (`grep -n "^import time" integrations/obs_ws.py`); add `import time` to the imports if it is missing.

- [ ] **Step 5: Handle the preview event**

In `_handle_event`, add a branch right after the `CurrentProgramSceneChanged` branch:

```python
    elif event_type == 'CurrentPreviewSceneChanged':
        with _cache_lock:
            _cache['preview_scene'] = data.get('sceneName', '')
```

And add `'CurrentPreviewSceneChanged'` to the `_NOTIFY_EVENTS` tuple so the `obs` SSE topic nudges pages when the preview moves.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_obs_ws_studio.py tests/test_obs_ws.py tests/test_obs_output.py tests/test_obs_cut.py -q -p no:warnings`
Expected: all PASS (the existing cut tests still pass because `switch_scene`'s behaviour is unchanged apart from the extra cache entry).

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check integrations/obs_ws.py tests/test_obs_ws_studio.py
git add integrations/obs_ws.py tests/test_obs_ws_studio.py
git commit -m "obs_ws: Studio Mode, preview, transition, chapter and screenshot helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: obs_ws meter events and `levels()`

**Files:**
- Modify: `integrations/obs_ws.py` (`EVENT_SUBS` ~line 61, identify ~line 991, `_handle_event`)
- Test: `tests/test_obs_ws_studio.py` (append)

**Interfaces:**
- Produces: `set_meter_events(on: bool) -> None` (sends a `Reidentify`, op 3, when connected; remembered across reconnects), `levels() -> tuple[dict[str, list[float]], float]` — `{input_name: [peak_mul_per_channel...]}` (multipliers 0..1) and the monotonic time of the last frame, `METER_EVENT_FLAG == 1 << 16`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_obs_ws_studio.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_obs_ws_studio.py -q -p no:warnings -k meter`
Expected: FAIL with `AttributeError: ... has no attribute 'set_meter_events'`.

- [ ] **Step 3: Implement**

Directly under the `EVENT_SUBS = ...` line add:

```python
# InputVolumeMeters is a high-volume subscription (~20 frames/s); only the
# producer console wants it, and only while a console is open.
METER_EVENT_FLAG = 1 << 16
_meter_events = False
_levels = {}            # inputName -> [peak multiplier per channel]
_levels_at = 0.0
_levels_lock = threading.Lock()


def _event_subs():
    return EVENT_SUBS | (METER_EVENT_FLAG if _meter_events else 0)


def set_meter_events(on):
    """Turn the audio meter event stream on/off with a Reidentify (op 3).
    Remembered, so a reconnect re-subscribes the same way."""
    global _meter_events
    _meter_events = bool(on)
    if _state == 'connected':
        try:
            _send({'op': 3, 'd': {'eventSubscriptions': _event_subs()}})
        except ObsUnavailable:
            pass


def levels():
    """({input: [peak per channel]}, monotonic time of the last frame)."""
    with _levels_lock:
        return {k: list(v) for k, v in _levels.items()}, _levels_at
```

`threading` is already imported at the top of the module (`_lock = threading.Lock()` uses it) — if `_levels_lock` lands above that import, move the block below the existing `_lock = threading.Lock()` line instead.

In the identify code change

```python
    ident = {'rpcVersion': _RPC_VERSION, 'eventSubscriptions': EVENT_SUBS}
```

to

```python
    ident = {'rpcVersion': _RPC_VERSION, 'eventSubscriptions': _event_subs()}
```

In `_handle_event` put `global _levels_at` as the first statement of the function (directly under its docstring), then add a branch before the `ExitStarted` branch:

```python
    elif event_type == 'InputVolumeMeters':
        peaks = {}
        for inp in data.get('inputs') or []:
            chans = inp.get('inputLevelsMul') or []
            peaks[inp.get('inputName', '')] = [
                float(c[1]) if len(c) > 1 else 0.0 for c in chans]
        with _levels_lock:
            _levels.clear()
            _levels.update(peaks)
            _levels_at = time.monotonic()
        return          # never _notify: 20 frames a second must not hit sqlite
```

The `return` matters: the function ends with `if event_type in _NOTIFY_EVENTS: _notify(event_type)`; meters are not in that tuple anyway, but returning early keeps the hot path short.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_obs_ws_studio.py tests/test_obs_ws.py -q -p no:warnings`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check integrations/obs_ws.py tests/test_obs_ws_studio.py
git add integrations/obs_ws.py tests/test_obs_ws_studio.py
git commit -m "obs_ws: opt-in InputVolumeMeters stream and levels()

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `producer` SSE topic

**Files:**
- Modify: `core/events.py:20-24`, `web/app/topics.js`
- Test: `tests/test_events.py` (append)

**Interfaces:**
- Produces: `events.topic_ok('producer') is True`; `/api/v1/events?topics=producer` accepted; `TOPICS` in `topics.js` includes `'producer'`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_events.py`:

```python
def test_producer_topic_is_accepted(client, dm_token):
    assert events.topic_ok('producer')
    with client.stream('GET', '/api/v1/events?topics=producer',
                       headers={'Authorization': f'Bearer {dm_token}'}) as r:
        assert r.status_code == 200
        first = next(r.iter_lines())
        assert 'hello' in first
```

If `tests/test_events.py` already has a test opening the stream, copy its exact pattern for reading the first frame instead of the `iter_lines` call above (the assertion is that the connection is accepted with a `hello` frame).

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_events.py -q -p no:warnings -k producer_topic`
Expected: FAIL — `topic_ok('producer')` is False (or the stream answers 400).

- [ ] **Step 3: Add the topic**

`core/events.py`: change the `TOPICS` set to

```python
TOPICS = {
    'nowplaying', 'queue', 'health', 'relay', 'obs', 'downloads', 'update',
    'netscan', 'dice', 'scene', 'server', 'producer',
    # parameterised: battlemap:<id> session:<id> character:<id> syncjob:<job> aijob:<id>
}
```

`web/app/topics.js`: add `'producer'` to the exported `TOPICS` array (keep the existing order, append at the end of the plain-topic list).

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_events.py tests/test_web_assets.py -q -p no:warnings`
Expected: all PASS (`test_web_assets` checks that every topic in `topics.js` is accepted by the server).

- [ ] **Step 5: Commit**

```bash
git add core/events.py web/app/topics.js tests/test_events.py
git commit -m "events: producer topic

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Producer router — console registry, Studio Mode lifecycle, auto-cam pause, state

**Files:**
- Create: `routers/producer.py`
- Modify: `routers/obs/__init__.py` (`auto_cam_on` ~line 456), `app.py` (router registration ~line 143)
- Test: `tests/test_producer_api.py`

**Interfaces:**
- Consumes: `routers.obs._active_session_id()`, `routers.obs._ordered_party()`, `routers.obs._scene_name_for(char)`, `routers.obs._cut_scene_name(key)`, `routers.obs.CUT_TARGETS`, `routers.obs.DM_TILE_ID`, `routers.obs.auto_cam_on()`, `routers.obs._emit(kind, **extra)`, obs_ws helpers from Tasks 1–2, `events.emit`.
- Produces (module `routers.producer`):
  - constants `PING_TTL_S = 45`, `STUDIO_OFF_GRACE_S = 10`, `PAUSE_KEY = 'obs_auto_cam_paused_by_producer'`
  - `console_count() -> int`, `open_console() -> str`, `ping_console(cid) -> bool`, `close_console(cid) -> None`, `producer_active() -> bool`
  - `shots() -> list[dict]` with keys `key, label, scene, kind ('special'|'player'|'dm'), built (bool), character_id (int|None)`
  - `shot(key) -> dict | None`
  - `state_doc() -> dict` (see Step 3)
  - `_sfx() -> str` (`':s<id>'` or `''`)
  - routes `POST /ttrpg/producer/api/session`, `POST .../session/ping`, `DELETE .../session/{console_id}`, `GET .../state`, `POST .../auto-cam-pause`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_producer_api.py`:

```python
"""Producer console API. obs_ws is stubbed at the function level (the same
idea as tests/test_obs_output.py); the settings table is the scratch DB's."""
import pytest

from core.db import db


@pytest.fixture()
def dm_client(legacy_app):
    from models.user import tblUsers
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm)
    db.session.commit()
    with legacy_app.test_client(user=dm) as c:
        yield c


@pytest.fixture()
def obs(monkeypatch):
    """Recording stub of every obs_ws call the producer router makes."""
    import integrations.obs_ws as obs_ws
    calls = []
    state = obs_ws._blank_cache()
    state.update({'scenes': ['ScenePlay Party', 'ScenePlay Map', 'Player - Carl', 'DM - Jankis'],
                  'current_scene': 'ScenePlay Party',
                  'transitions': [{'name': 'Cut', 'fixed': True}, {'name': 'Fade', 'fixed': False}],
                  'current_transition': 'Cut', 'transition_ms': 300})
    flags = {'connected': True}

    def rec(name, ret=None):
        def f(*a, **k):
            calls.append((name,) + a)
            return ret
        return f

    monkeypatch.setattr(obs_ws, 'connected', lambda: flags['connected'])
    monkeypatch.setattr(obs_ws, 'current_state', lambda: dict(state))
    monkeypatch.setattr(obs_ws, 'set_studio_mode', rec('studio'))
    monkeypatch.setattr(obs_ws, 'set_meter_events', rec('meters'))
    monkeypatch.setattr(obs_ws, 'set_preview_scene',
                        lambda name, timeout=3: (calls.append(('preview', name)), state.__setitem__('preview_scene', name)))
    monkeypatch.setattr(obs_ws, 'preview_scene', lambda: state['preview_scene'])
    monkeypatch.setattr(obs_ws, 'set_transition', rec('transition'))
    monkeypatch.setattr(obs_ws, 'trigger_transition', rec('take'))
    monkeypatch.setattr(obs_ws, 'record_chapter', rec('chapter'))
    monkeypatch.setattr(obs_ws, 'screenshot', rec('shot', b'\xff\xd8jpeg'))
    monkeypatch.setattr(obs_ws, 'levels', lambda: ({'ScenePlay Music': [0.5]}, 1.0))
    return {'calls': calls, 'state': state, 'flags': flags}


@pytest.fixture()
def fresh(monkeypatch):
    """No consoles registered, no off-timer, nothing armed."""
    import routers.producer as p
    monkeypatch.setattr(p, '_consoles', {})
    monkeypatch.setattr(p, '_off_timer', None)
    monkeypatch.setattr(p, '_armed', {'key': None})
    yield p
    if p._off_timer is not None:          # a real Timer scheduled by a test: never let it fire later
        p._off_timer.cancel()
        p._off_timer = None


def _party(monkeypatch, names=('Carl',)):
    """Stand in for the OBS router's party ordering: one on-stream player per
    name plus the DM tile, with the same scene naming the router uses."""
    import routers.obs as obs

    class C:
        def __init__(self, cid, name):
            self.character_id, self.name = cid, name

    chars = [C(i + 1, n) for i, n in enumerate(names)] + [C(obs.DM_TILE_ID, 'Jankis')]
    monkeypatch.setattr(obs, '_ordered_party', lambda include_offstage=False: chars)
    return chars


def test_open_turns_studio_mode_on_and_pauses_auto_cam(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/session')
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] and body['console_id'] and body['consoles'] == 1
    assert ('studio', True) in obs['calls'] and ('meters', True) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '1'
    assert fresh.producer_active() is True


def test_auto_cam_is_off_while_producer_pauses_it(dm_client, obs, fresh, monkeypatch):
    import routers.obs as ro
    from sql import appsettingSet
    appsettingSet('obs_auto_cam', '1')
    assert ro.auto_cam_on() is True
    appsettingSet(fresh.PAUSE_KEY, '1')
    assert ro.auto_cam_on() is False
    appsettingSet(fresh.PAUSE_KEY, '0')
    assert ro.auto_cam_on() is True


def test_pause_toggle(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': False})
    assert r.get_json() == {'ok': True, 'paused': False}
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'
    r = dm_client.post('/ttrpg/producer/api/auto-cam-pause', json={'paused': True})
    assert r.get_json()['paused'] is True and appsettingGet(fresh.PAUSE_KEY, '0') == '1'


def test_last_close_turns_studio_mode_off_after_grace(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    timers = []

    class FakeTimer:
        def __init__(self, secs, fn):
            timers.append((secs, fn)); self.daemon = False
        def start(self): pass
        def cancel(self): pass

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    cid2 = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    dm_client.delete(f'/ttrpg/producer/api/session/{cid}')
    assert timers == []                                   # one console still open
    dm_client.delete(f'/ttrpg/producer/api/session/{cid2}')
    assert len(timers) == 1 and timers[0][0] == fresh.STUDIO_OFF_GRACE_S
    obs['calls'].clear()
    timers[0][1]()                                        # grace elapsed
    assert ('studio', False) in obs['calls'] and ('meters', False) in obs['calls']
    assert appsettingGet(fresh.PAUSE_KEY, '0') == '0'


def test_reopen_within_grace_cancels_the_off_timer(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    cancelled = []

    class FakeTimer:
        def __init__(self, secs, fn): self.daemon = False
        def start(self): pass
        def cancel(self): cancelled.append(True)

    monkeypatch.setattr(fresh.threading, 'Timer', FakeTimer)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    dm_client.delete(f'/ttrpg/producer/api/session/{cid}')
    dm_client.post('/ttrpg/producer/api/session')
    assert cancelled == [True]


def test_stale_console_is_reaped_after_ping_ttl(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    cid = dm_client.post('/ttrpg/producer/api/session').get_json()['console_id']
    assert dm_client.post('/ttrpg/producer/api/session/ping', json={'console_id': cid}).get_json()['ok'] is True
    fresh._consoles[cid] -= fresh.PING_TTL_S + 1
    assert fresh.console_count() == 0
    assert dm_client.post('/ttrpg/producer/api/session/ping', json={'console_id': cid}).get_json()['ok'] is False


def test_state_document(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.get('/ttrpg/producer/api/state')
    d = r.get_json()
    assert d['connected'] is True and d['program'] == 'ScenePlay Party' and d['preview'] == ''
    keys = [s['key'] for s in d['shots']]
    assert keys == ['party', 'map', 'char:1', 'dm', 'pre', 'intermission', 'post']
    carl = next(s for s in d['shots'] if s['key'] == 'char:1')
    assert carl == {'key': 'char:1', 'label': 'Carl', 'scene': 'Player - Carl',
                    'kind': 'player', 'built': True, 'character_id': 1}
    pre = next(s for s in d['shots'] if s['key'] == 'pre')
    assert pre['built'] is False and pre['kind'] == 'special'
    assert d['transitions'] == ['Cut', 'Fade'] and d['transition'] == 'Cut' and d['transition_ms'] == 300
    assert d['consoles'] == 0 and d['armed'] is None and d['auto_cam_paused'] is False
    assert set(d) >= {'studio_mode', 'recording', 'streaming', 'record_timecode', 'stream_timecode',
                      'last_switch', 'countdown_until', 'clock_start', 'markers', 'session'}


def test_state_needs_dm(legacy_app, obs, fresh):
    from models.user import tblUsers
    pl = tblUsers(username='pl', display_name='P', password_hash='x', role='player', active=1,
                  created_at='2026-01-01 00:00:00')
    db.session.add(pl); db.session.commit()
    with legacy_app.test_client(user=pl) as c:
        assert c.get('/ttrpg/producer/api/state').status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'routers.producer'`.

- [ ] **Step 3: Create `routers/producer.py`**

```python
"""Producer console API — the live surface a second person runs the stream
from (/ttrpg/producer, spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md).

Lifecycle: the first console to open turns OBS Studio Mode and the audio
meter stream on and pauses auto-cam; STUDIO_OFF_GRACE_S after the last console
closes (or stops pinging) everything is put back. The rest of the OBS
integration keeps switching Program directly, which Studio Mode allows.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends

import core.events as events
import integrations.obs_ws as obs_ws
import routers.obs as obs
from routers._util import json_body
from security.deps import require_dm
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)
router = APIRouter(prefix='/ttrpg/producer/api')

PING_TTL_S = 45              # a console that stops pinging is gone
STUDIO_OFF_GRACE_S = 10      # reconnect window before Studio Mode is dropped
PAUSE_KEY = 'obs_auto_cam_paused_by_producer'
SPECIALS_FRONT = ('party', 'map')
SPECIALS_BACK = ('pre', 'intermission', 'post')

_consoles = {}               # console_id -> last ping (time.monotonic())
_lock = threading.Lock()
_off_timer = None
_armed = {'key': None}       # shot key currently in Preview (by this router)


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _sfx():
    sid = obs._active_session_id()
    return f':s{sid}' if sid else ''


def _emit_state():
    try:
        events.emit('producer', {'kind': 'state'})
    except Exception:
        pass


# ── console registry ─────────────────────────────────────────────────────────

def console_count():
    now = time.monotonic()
    with _lock:
        stale = [cid for cid, at in _consoles.items() if now - at > PING_TTL_S]
        for cid in stale:
            del _consoles[cid]
        n = len(_consoles)
    if stale and n == 0:
        _schedule_off()
    return n


def producer_active():
    return console_count() > 0


def _studio(on):
    if not obs_ws.connected():
        return
    try:
        obs_ws.set_studio_mode(on)
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        log.info('Studio Mode %s failed: %s', 'on' if on else 'off', exc)
    try:
        obs_ws.set_meter_events(on)
    except Exception as exc:
        log.info('meter events %s failed: %s', on, exc)


def _off_if_idle():
    global _off_timer
    _off_timer = None
    if console_count():
        return
    appsettingSet(PAUSE_KEY, '0')
    _armed['key'] = None
    _studio(False)
    _emit_state()


def _schedule_off():
    global _off_timer
    if _off_timer is not None:
        _off_timer.cancel()
    t = threading.Timer(STUDIO_OFF_GRACE_S, _off_if_idle)
    t.daemon = True
    t.start()
    _off_timer = t


def open_console():
    global _off_timer
    cid = uuid.uuid4().hex[:12]
    first = console_count() == 0
    with _lock:
        _consoles[cid] = time.monotonic()
    if _off_timer is not None:
        _off_timer.cancel()
        _off_timer = None
    if first:
        appsettingSet(PAUSE_KEY, '1')
        _studio(True)
    if not (appsettingGet('producer_clock_start' + _sfx(), '') or '').strip():
        appsettingSet('producer_clock_start' + _sfx(), _now())
    _emit_state()
    return cid


def ping_console(cid):
    with _lock:
        if cid in _consoles:
            _consoles[cid] = time.monotonic()
            return True
    return False


def close_console(cid):
    with _lock:
        _consoles.pop(cid, None)
    if console_count() == 0:
        _schedule_off()
    _emit_state()


# ── shots ────────────────────────────────────────────────────────────────────

def shots():
    """Every shot the console can arm, in tile order: party, map, the players
    and the DM (the number keys count these), then the show cards."""
    built = set(obs_ws.current_state().get('scenes') or [])
    out = []

    def special(key):
        scene = obs._cut_scene_name(key)
        out.append({'key': key, 'label': obs.CUT_TARGETS[key][1], 'scene': scene,
                    'kind': 'special', 'built': scene in built, 'character_id': None})

    for key in SPECIALS_FRONT:
        special(key)
    for char in obs._ordered_party():
        is_dm = char.character_id == obs.DM_TILE_ID
        scene = obs._scene_name_for(char)
        out.append({'key': 'dm' if is_dm else f'char:{char.character_id}',
                    'label': char.name, 'scene': scene,
                    'kind': 'dm' if is_dm else 'player', 'built': scene in built,
                    'character_id': char.character_id})
    for key in SPECIALS_BACK:
        special(key)
    return out


def shot(key):
    for s in shots():
        if s['key'] == key:
            return s
    return None


# ── state ────────────────────────────────────────────────────────────────────

def _markers():
    try:
        return json.loads(appsettingGet('producer_markers' + _sfx(), '') or '[]')
    except ValueError:
        return []


def _session_info():
    from models.ttrpg import tblSessions
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return None
    return {'id': sess.session_id, 'title': sess.title, 'number': sess.session_number}


def state_doc():
    snap = obs_ws.current_state()
    sfx = _sfx()
    return {
        'connected': obs_ws.connected(),
        'studio_mode': bool(snap.get('studio_mode')),
        'program': snap.get('current_scene', ''),
        'preview': snap.get('preview_scene', ''),
        'armed': _armed['key'],
        'shots': shots(),
        'transitions': [t['name'] for t in snap.get('transitions') or []],
        'transition': snap.get('current_transition', ''),
        'transition_ms': snap.get('transition_ms', 0),
        'recording': bool(snap.get('recording')),
        'streaming': bool(snap.get('streaming')),
        'record_timecode': snap.get('record_timecode', ''),
        'stream_timecode': snap.get('stream_timecode', ''),
        'last_switch': snap.get('last_switch'),
        'auto_cam': obs.auto_cam_setting(),
        'auto_cam_paused': (appsettingGet(PAUSE_KEY, '0') or '0') == '1',
        'countdown_until': appsettingGet('producer_countdown_until' + sfx, '') or '',
        'clock_start': appsettingGet('producer_clock_start' + sfx, '') or '',
        'markers': _markers(),
        'consoles': console_count(),
        'session': _session_info(),
    }


# ── routes ───────────────────────────────────────────────────────────────────

@router.post('/session')
def api_session_open(user=Depends(require_dm)):
    return {'ok': True, 'console_id': open_console(), 'consoles': console_count()}


@router.post('/session/ping')
def api_session_ping(data: dict = Depends(json_body), user=Depends(require_dm)):
    return {'ok': ping_console(str(data.get('console_id', ''))), 'consoles': console_count()}


@router.delete('/session/{console_id}')
def api_session_close(console_id: str, user=Depends(require_dm)):
    close_console(console_id)
    return {'ok': True, 'consoles': console_count()}


@router.get('/state')
def api_state(user=Depends(require_dm)):
    return state_doc()


@router.post('/auto-cam-pause')
def api_auto_cam_pause(data: dict = Depends(json_body), user=Depends(require_dm)):
    paused = bool(data.get('paused', True))
    appsettingSet(PAUSE_KEY, '1' if paused else '0')
    _emit_state()
    return {'ok': True, 'paused': paused}
```

- [ ] **Step 4: Teach the OBS router about the pause and expose the raw auto-cam setting**

In `routers/obs/__init__.py` replace

```python
def auto_cam_on():
    return (appsettingGet('obs_auto_cam', '0') or '0') == '1'
```

with

```python
def auto_cam_setting():
    """The DM's auto-cam switch as saved, regardless of any producer pause."""
    return (appsettingGet('obs_auto_cam', '0') or '0') == '1'


def auto_cam_on():
    """Auto-cam runs only while the DM has it on AND no producer console has
    paused it (routers/producer.py sets the pause key while a console is open)."""
    if (appsettingGet('obs_auto_cam_paused_by_producer', '0') or '0') == '1':
        return False
    return auto_cam_setting()
```

Then run `grep -n "auto_cam_on()" routers/obs/__init__.py` and, for the ONE call that builds the Broadcast page data (the `'auto_cam': auto_cam_on(),` entry inside the `broadcast` page-data function near line 140–190, if present), change it to `auto_cam_setting()` so the DM's checkbox keeps showing what they saved. Leave every other call as `auto_cam_on()`.

- [ ] **Step 5: Register the router**

In `app.py`, directly after `app.include_router(events_router.router)` (line ~146) add:

```python
    import routers.producer as producer
    app.include_router(producer.router)
```

(If the file registers the OBS router through a loop later, this explicit include is still correct: the producer router has its own prefix and no overlap.)

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py tests/test_obs_auto_cam.py tests/test_obs_toggle.py -q -p no:warnings`
Expected: all PASS.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check routers/producer.py routers/obs/__init__.py app.py tests/test_producer_api.py
git add routers/producer.py routers/obs/__init__.py app.py tests/test_producer_api.py
git commit -m "producer: console registry, Studio Mode lifecycle, auto-cam pause, state

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Arm, Take, Auto, transition; tag Broadcast page cuts

**Files:**
- Modify: `routers/producer.py` (append), `routers/obs/__init__.py` (`_cut` ~line 2127)
- Test: `tests/test_producer_api.py` (append)

**Interfaces:**
- Consumes: Task 4 module state (`_armed`, `shot()`, `_emit_state()`), `obs._emit`, obs_ws helpers.
- Produces routes: `POST /ttrpg/producer/api/arm {key}`, `POST .../take {transition?, ms?}`, `POST .../auto {ms?}`, `POST .../transition {name, ms?}`. `_cut()` in the OBS router now calls `obs_ws.switch_scene(scene, by='broadcast')`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_producer_api.py`:

```python
def test_arm_sets_preview(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'char:1'})
    assert r.get_json() == {'ok': True, 'armed': 'char:1', 'scene': 'Player - Carl'}
    assert ('preview', 'Player - Carl') in obs['calls']
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] == 'char:1'


def test_arm_unknown_and_unbuilt(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    assert dm_client.post('/ttrpg/producer/api/arm', json={'key': 'nope'}).status_code == 400
    r = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'pre'})
    body = r.get_json()
    assert body['ok'] is False and 'Build' in body['error']
    assert not any(c[0] == 'preview' for c in obs['calls'])


def test_arm_when_disconnected(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    obs['flags']['connected'] = False
    body = dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'}).get_json()
    assert body == {'ok': False, 'error': 'OBS is not connected.'}


def test_take_with_nothing_armed(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body == {'ok': False, 'error': 'Nothing armed.'}
    assert not any(c[0] == 'take' for c in obs['calls'])


def test_take_uses_chosen_transition_and_tags_the_cut(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import routers.obs as ro
    emitted = []
    monkeypatch.setattr(ro, '_emit', lambda kind, **x: emitted.append((kind, x)))
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'map'})
    r = dm_client.post('/ttrpg/producer/api/take', json={'transition': 'Cut'})
    assert r.get_json() == {'ok': True, 'scene': 'ScenePlay Map', 'transition': 'Cut'}
    assert ('transition', 'Cut', None) in obs['calls'] and ('take',) in obs['calls']
    assert ('cut', {'target': 'map', 'scene': 'ScenePlay Map', 'by': 'producer'}) in emitted
    assert dm_client.get('/ttrpg/producer/api/state').get_json()['armed'] is None


def test_auto_is_a_fade_take(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'dm'})
    r = dm_client.post('/ttrpg/producer/api/auto', json={'ms': 500})
    assert r.get_json() == {'ok': True, 'scene': 'DM - Jankis', 'transition': 'Fade'}
    assert ('transition', 'Fade', 500) in obs['calls']


def test_take_obs_rejection_is_reported(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    import integrations.obs_ws as obs_ws
    dm_client.post('/ttrpg/producer/api/arm', json={'key': 'party'})

    def boom(timeout=3):
        raise obs_ws.ObsRejected(500, 'studio mode is off')
    monkeypatch.setattr(obs_ws, 'trigger_transition', boom)
    body = dm_client.post('/ttrpg/producer/api/take', json={}).get_json()
    assert body['ok'] is False and 'studio mode is off' in body['error']


def test_transition_default(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    r = dm_client.post('/ttrpg/producer/api/transition', json={'name': 'Fade', 'ms': 700})
    assert r.get_json() == {'ok': True, 'transition': 'Fade', 'ms': 700}
    assert ('transition', 'Fade', 700) in obs['calls']


def test_broadcast_cut_is_tagged(dm_client, obs, fresh, monkeypatch):
    """The OBS router's own cut tells switch_scene who did it."""
    import integrations.obs_ws as obs_ws
    import routers.obs as ro
    seen = []
    monkeypatch.setattr(obs_ws, 'switch_scene', lambda scene, **k: seen.append((scene, k.get('by'))))
    monkeypatch.setattr(obs_ws, 'scene_list', lambda refresh=False: (['ScenePlay Map'], 'ScenePlay Party'))
    monkeypatch.setattr(ro, 'map_scene_name', lambda: 'ScenePlay Map')
    monkeypatch.setattr(ro, '_special_scene', lambda special: '')
    r = dm_client.post('/ttrpg/obs/api/cut/map')
    assert r.status_code == 200 and seen == [('ScenePlay Map', 'broadcast')]
```

If `_cut` in your checkout calls other `obs_ws` functions before the switch (scene audio, un-pinning), stub each with `monkeypatch.setattr(obs_ws, '<name>', lambda *a, **k: None)` until the request returns 200; the assertion under test is only the `by='broadcast'` tag.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings -k "arm or take or auto_is or transition_default or broadcast_cut"`
Expected: FAIL — 404s for the new routes; `test_broadcast_cut_is_tagged` fails with `seen == [('ScenePlay Map', None)]`.

- [ ] **Step 3: Append the switching routes to `routers/producer.py`**

First change the import line `from security.deps import require_dm` to `from security.deps import ApiError, require_dm`. Then append:

```python
# ── switching ────────────────────────────────────────────────────────────────

def _obs_error(exc):
    if isinstance(exc, obs_ws.ObsRejected):
        return f'OBS refused: {exc.comment or exc}'
    return 'Lost the OBS connection.'


@router.post('/arm')
def api_arm(data: dict = Depends(json_body), user=Depends(require_dm)):
    key = str(data.get('key', '') or '')
    s = shot(key)
    if not s:
        raise ApiError(400, f'Unknown shot {key!r}', code='bad_shot')
    if not s['built']:
        return {'ok': False, 'error': f"{s['label']}: scene not built yet — run Build on the Broadcast page."}
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    try:
        obs_ws.set_preview_scene(s['scene'])
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    _armed['key'] = key
    _emit_state()
    return {'ok': True, 'armed': key, 'scene': s['scene']}


def _take(transition, ms):
    if not obs_ws.connected():
        return {'ok': False, 'error': 'OBS is not connected.'}
    scene = obs_ws.preview_scene()
    if not scene:
        return {'ok': False, 'error': 'Nothing armed.'}
    try:
        if transition:
            obs_ws.set_transition(transition, ms)
        obs_ws.trigger_transition()
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
        return {'ok': False, 'error': _obs_error(exc)}
    key = _armed['key'] or ''
    _armed['key'] = None
    obs._emit('cut', target=key, scene=scene, by='producer')
    _emit_state()
    return {'ok': True, 'scene': scene, 'transition': transition}


def _ms(data, default=None):
    try:
        v = int(data.get('ms'))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


@router.post('/take')
def api_take(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Preview -> Program with the transition named in the body (or whatever
    OBS has selected when none is given)."""
    name = (data.get('transition') or '').strip() or None
    return _take(name, _ms(data))


@router.post('/auto')
def api_auto(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Preview -> Program with a fade (default 300 ms)."""
    return _take('Fade', _ms(data, 300))


@router.post('/transition')
def api_transition(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Pick the default transition for the next Take without taking."""
    name = (data.get('name') or '').strip()
    if not name:
        raise ApiError(400, 'transition name required', code='bad_request')
    ms = _ms(data)
    if obs_ws.connected():
        try:
            obs_ws.set_transition(name, ms)
        except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
            return {'ok': False, 'error': _obs_error(exc)}
    return {'ok': True, 'transition': name, 'ms': ms}
```

- [ ] **Step 4: Tag the Broadcast page cut**

In `routers/obs/__init__.py` inside `_cut(key)` change the line

```python
        obs_ws.switch_scene(scene)
```

(the one directly below the `ensure_show_scenes()` block, ~line 2127) to

```python
        obs_ws.switch_scene(scene, by='broadcast')
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py tests/test_obs_cut.py -q -p no:warnings`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check routers/producer.py routers/obs/__init__.py tests/test_producer_api.py
git add routers/producer.py routers/obs/__init__.py tests/test_producer_api.py
git commit -m "producer: arm / take / auto / transition; broadcast cuts tagged

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Countdown, clock and markers

**Files:**
- Modify: `routers/producer.py` (append)
- Test: `tests/test_producer_api.py` (append)

**Interfaces:**
- Produces routes: `POST /ttrpg/producer/api/countdown {seconds}|{until}|{clear:true}`, `POST .../clock/reset`, `POST .../marker {note}`, `GET .../markers`, `DELETE .../markers`. Settings keys `producer_countdown_until<sfx>` (local timestamp string), `producer_clock_start<sfx>`, `producer_markers<sfx>` (JSON list of `{at, timecode, note, recording}`, newest last, max 200).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_producer_api.py`:

```python
def test_countdown_seconds_until_and_clear(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'seconds': 600})
    body = r.get_json()
    assert body['ok'] and len(body['until']) == 19
    assert appsettingGet('producer_countdown_until', '') == body['until']
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'until': '2030-01-01 20:15:00'})
    assert r.get_json()['until'] == '2030-01-01 20:15:00'
    r = dm_client.post('/ttrpg/producer/api/countdown', json={'clear': True})
    assert r.get_json() == {'ok': True, 'until': ''}
    assert appsettingGet('producer_countdown_until', '') == ''


def test_countdown_rejects_garbage(dm_client, obs, fresh):
    assert dm_client.post('/ttrpg/producer/api/countdown', json={'until': 'soon'}).status_code == 400
    assert dm_client.post('/ttrpg/producer/api/countdown', json={}).status_code == 400


def test_clock_reset(dm_client, obs, fresh, monkeypatch):
    from sql import appsettingGet
    _party(monkeypatch)
    dm_client.post('/ttrpg/producer/api/session')
    first = appsettingGet('producer_clock_start', '')
    assert len(first) == 19
    r = dm_client.post('/ttrpg/producer/api/clock/reset')
    assert r.get_json()['ok'] and len(r.get_json()['clock_start']) == 19


def test_marker_while_recording_creates_chapter(dm_client, obs, fresh):
    obs['state']['recording'] = True
    obs['state']['record_timecode'] = '00:12:03.500'
    r = dm_client.post('/ttrpg/producer/api/marker', json={'note': 'Dragon appears'})
    body = r.get_json()
    assert body['ok'] and body['marker']['note'] == 'Dragon appears'
    assert body['marker']['recording'] is True and body['marker']['timecode'] == '00:12:03.500'
    assert ('chapter', 'Dragon appears') in obs['calls']
    assert dm_client.get('/ttrpg/producer/api/markers').get_json()['markers'][-1]['note'] == 'Dragon appears'


def test_marker_without_recording_is_kept_but_no_chapter(dm_client, obs, fresh):
    body = dm_client.post('/ttrpg/producer/api/marker', json={'note': ''}).get_json()
    assert body['ok'] and body['marker']['note'] == 'Marker' and body['marker']['recording'] is False
    assert not any(c[0] == 'chapter' for c in obs['calls'])


def test_marker_chapter_rejection_is_not_fatal(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    obs['state']['recording'] = True

    def boom(name, timeout=3):
        raise obs_ws.ObsRejected(501, 'no chapters in this container')
    monkeypatch.setattr(obs_ws, 'record_chapter', boom)
    body = dm_client.post('/ttrpg/producer/api/marker', json={'note': 'x'}).get_json()
    assert body['ok'] and body['marker']['chapter'] is False and 'container' in body['warning']


def test_markers_capped_and_clearable(dm_client, obs, fresh):
    for i in range(205):
        dm_client.post('/ttrpg/producer/api/marker', json={'note': str(i)})
    ms = dm_client.get('/ttrpg/producer/api/markers').get_json()['markers']
    assert len(ms) == 200 and ms[0]['note'] == '5' and ms[-1]['note'] == '204'
    assert dm_client.delete('/ttrpg/producer/api/markers').get_json() == {'ok': True}
    assert dm_client.get('/ttrpg/producer/api/markers').get_json()['markers'] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings -k "countdown or clock or marker"`
Expected: FAIL with 404 / 405 on the new routes.

- [ ] **Step 3: Append to `routers/producer.py`**

```python
# ── clocks and markers ───────────────────────────────────────────────────────

MARKERS_MAX = 200
_TS = '%Y-%m-%d %H:%M:%S'


@router.post('/countdown')
def api_countdown(data: dict = Depends(json_body), user=Depends(require_dm)):
    """{'seconds': n} counts down from now; {'until': 'YYYY-MM-DD HH:MM:SS'}
    sets an absolute end; {'clear': true} removes it."""
    from datetime import timedelta
    key = 'producer_countdown_until' + _sfx()
    if data.get('clear'):
        appsettingSet(key, '')
        _emit_state()
        return {'ok': True, 'until': ''}
    until = None
    if data.get('until'):
        try:
            until = datetime.strptime(str(data['until']).strip(), _TS)
        except ValueError:
            raise ApiError(400, 'until must be YYYY-MM-DD HH:MM:SS', code='bad_request')
    elif data.get('seconds') is not None:
        try:
            secs = int(data['seconds'])
        except (TypeError, ValueError):
            raise ApiError(400, 'seconds must be an integer', code='bad_request')
        if secs <= 0:
            raise ApiError(400, 'seconds must be positive', code='bad_request')
        until = datetime.now() + timedelta(seconds=secs)
    if until is None:
        raise ApiError(400, 'seconds, until or clear required', code='bad_request')
    text = until.strftime(_TS)
    appsettingSet(key, text)
    _emit_state()
    return {'ok': True, 'until': text}


@router.post('/clock/reset')
def api_clock_reset(user=Depends(require_dm)):
    now = _now()
    appsettingSet('producer_clock_start' + _sfx(), now)
    _emit_state()
    return {'ok': True, 'clock_start': now}


def _save_markers(rows):
    appsettingSet('producer_markers' + _sfx(), json.dumps(rows[-MARKERS_MAX:]))


@router.post('/marker')
def api_marker(data: dict = Depends(json_body), user=Depends(require_dm)):
    """Stamp the moment: a chapter in the recording when one is running, and
    always a row in the session's marker list (for the edit later)."""
    note = (str(data.get('note', '') or '')).strip()[:200] or 'Marker'
    snap = obs_ws.current_state()
    recording = bool(snap.get('recording'))
    marker = {'at': _now(), 'timecode': snap.get('record_timecode', '') if recording else '',
              'note': note, 'recording': recording, 'chapter': False}
    warning = ''
    if recording and obs_ws.connected():
        try:
            obs_ws.record_chapter(note)
            marker['chapter'] = True
        except (obs_ws.ObsUnavailable, obs_ws.ObsRejected) as exc:
            warning = f'Marker saved, but OBS did not add a chapter: {getattr(exc, "comment", "") or exc}'
    rows = _markers()
    rows.append(marker)
    _save_markers(rows)
    _emit_state()
    out = {'ok': True, 'marker': marker}
    if warning:
        out['warning'] = warning
    return out


@router.get('/markers')
def api_markers(user=Depends(require_dm)):
    return {'markers': _markers()}


@router.delete('/markers')
def api_markers_clear(user=Depends(require_dm)):
    _save_markers([])
    _emit_state()
    return {'ok': True}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check routers/producer.py tests/test_producer_api.py
git add routers/producer.py tests/test_producer_api.py
git commit -m "producer: countdown, session clock, recording markers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Snapshot and level endpoints

**Files:**
- Modify: `routers/producer.py` (append)
- Test: `tests/test_producer_api.py` (append)

**Interfaces:**
- Produces routes: `GET /ttrpg/producer/api/snap/{target}` → `image/jpeg` bytes, `Cache-Control: no-store`; 204 when OBS is disconnected or sent nothing; 404 for an unknown target. Targets: `program`, `preview`, or any shot key from `shots()`. `GET .../levels` → `{'levels': {input: [peak...]}, 'age_ms': int}`.
- Both are `GET`, so the console may pass the JWT as `?token=` (allowed on GET by `security/deps.py`), which is what `<img src>` needs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_producer_api.py`:

```python
def test_snapshot_program_preview_and_shot(dm_client, obs, fresh, monkeypatch):
    _party(monkeypatch)
    obs['state']['preview_scene'] = 'Player - Carl'
    r = dm_client.get('/ttrpg/producer/api/snap/program')
    assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg'
    assert r.headers['cache-control'] == 'no-store' and r.data.startswith(b'\xff\xd8')
    assert ('shot', 'ScenePlay Party') in obs['calls']
    dm_client.get('/ttrpg/producer/api/snap/preview')
    assert ('shot', 'Player - Carl') in obs['calls']
    dm_client.get('/ttrpg/producer/api/snap/dm')
    assert ('shot', 'DM - Jankis') in obs['calls']


def test_snapshot_edge_cases(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    _party(monkeypatch)
    assert dm_client.get('/ttrpg/producer/api/snap/nope').status_code == 404
    obs['state']['preview_scene'] = ''
    assert dm_client.get('/ttrpg/producer/api/snap/preview').status_code == 204
    monkeypatch.setattr(obs_ws, 'screenshot', lambda *a, **k: b'')
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204
    obs['flags']['connected'] = False
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204


def test_snapshot_obs_failure_is_204(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    _party(monkeypatch)

    def boom(*a, **k):
        raise obs_ws.ObsUnavailable('timeout')
    monkeypatch.setattr(obs_ws, 'screenshot', boom)
    assert dm_client.get('/ttrpg/producer/api/snap/program').status_code == 204


def test_levels(dm_client, obs, fresh, monkeypatch):
    import integrations.obs_ws as obs_ws
    import time
    monkeypatch.setattr(obs_ws, 'levels', lambda: ({'ScenePlay Music': [0.5, 0.4]}, time.monotonic() - 0.25))
    body = dm_client.get('/ttrpg/producer/api/levels').get_json()
    assert body['levels'] == {'ScenePlay Music': [0.5, 0.4]} and 200 <= body['age_ms'] <= 2000
```

The `LegacyClient` response exposes raw bytes as `.data`; if the test fails with `AttributeError: 'data'`, check `tests/conftest.py` for the bytes attribute the `_LegacyResp` class provides (`.content` or `.data`) and use that one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings -k "snapshot or levels"`
Expected: FAIL with 404 on `/snap/program` and `/levels`.

- [ ] **Step 3: Append to `routers/producer.py`**

First add `from fastapi.responses import Response` under the `from fastapi import APIRouter, Depends` line. Then append:

```python
# ── multiview ────────────────────────────────────────────────────────────────

SNAP_WIDTH = 320


def _snap_source(target):
    snap = obs_ws.current_state()
    if target == 'program':
        return snap.get('current_scene', '')
    if target == 'preview':
        return snap.get('preview_scene', '')
    s = shot(target)
    if s is None:
        raise ApiError(404, f'Unknown snapshot target {target!r}', code='not_found')
    return s['scene']


@router.get('/snap/{target}')
def api_snap(target: str, user=Depends(require_dm)):
    """One JPEG frame of Program, Preview or a shot's scene. 204 (no body)
    whenever OBS cannot give one — the console keeps the last frame."""
    source = _snap_source(target)
    headers = {'Cache-Control': 'no-store'}
    if not source or not obs_ws.connected():
        return Response(status_code=204, headers=headers)
    try:
        data = obs_ws.screenshot(source, width=SNAP_WIDTH)
    except (obs_ws.ObsUnavailable, obs_ws.ObsRejected):
        data = b''
    if not data:
        return Response(status_code=204, headers=headers)
    return Response(content=data, media_type='image/jpeg', headers=headers)


@router.get('/levels')
def api_levels(user=Depends(require_dm)):
    lv, at = obs_ws.levels()
    age_ms = int((time.monotonic() - at) * 1000) if at else 0
    return {'levels': lv, 'age_ms': max(0, age_ms)}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_producer_api.py -q -p no:warnings`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check routers/producer.py tests/test_producer_api.py
git add routers/producer.py tests/test_producer_api.py
git commit -m "producer: snapshot and audio level endpoints

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The console page

**Files:**
- Create: `web/app/views/ttrpg/producer/index.js`, `web/app/views/ttrpg/producer/template.js`, `web/app/views/ttrpg/producer/console.js`, `web/css/views/producer.css`
- Modify: `web/app/routes.js` (add one route), `web/app/views/ttrpg/obs_broadcast/template.js` (header link, line ~657), `routers/obs/__init__.py` (`producer_url` in the page data)
- Test: `tests/test_web_assets.py` (already walks routes and modules), `tests/test_obs_overlays.py` untouched

**Interfaces:**
- Consumes: routes above; `api.get/post/del`, `sse.subscribe(topic, fn, {fallback})`, `store.get('nowPlaying')`, `toast`, `loadCss`, `ctx.on/every/signal`, `auth.token()` for `<img>` URLs.
- Produces: route `/ttrpg/producer` (auth `dm`, layout `ttrpg`, bodyClass `producer`); the Broadcast page shows an "Open producer console" link.

- [ ] **Step 1: Write the failing assertion**

Append to `tests/test_web_assets.py`:

```python
def test_producer_console_route_and_modules(client, dm_token):
    r = client.get('/ttrpg/producer', headers={'Authorization': f'Bearer {dm_token}'})
    assert r.status_code == 200 and '/app/main.js' in r.text
    for f in ('web/app/views/ttrpg/producer/index.js', 'web/app/views/ttrpg/producer/template.js',
              'web/app/views/ttrpg/producer/console.js', 'web/css/views/producer.css'):
        assert __import__('os').path.exists(f), f
    routes = open('web/app/routes.js', encoding='utf-8').read()
    assert "path: '/ttrpg/producer'" in routes and "bodyClass: 'producer'" in routes
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_assets.py -q -p no:warnings -k producer_console`
Expected: FAIL on the missing files.

- [ ] **Step 3: Route**

In `web/app/routes.js`, after the `/ttrpg/register` line add:

```js
  { path: '/ttrpg/producer', view: V('ttrpg/producer/index'), layout: 'ttrpg', auth: 'dm', bodyClass: 'producer' },
```

- [ ] **Step 4: CSS — `web/css/views/producer.css`**

```css
/* Producer console: a switcher desk on a laptop, side by side with the stream. */
body.producer .container, body.producer .container-fluid { max-width: none; }
.pc { display: grid; gap: .6rem; grid-template-columns: 1fr 1fr 16rem; grid-template-areas:
  "pvw pgm side" "shots shots side" "sp audio audio"; }
@media (max-width: 1100px) { .pc { grid-template-columns: 1fr 1fr; grid-template-areas:
  "pvw pgm" "side side" "shots shots" "sp audio"; } }
@media (max-width: 720px) { .pc { grid-template-columns: 1fr; grid-template-areas:
  "pgm" "pvw" "side" "shots" "sp" "audio"; } }
.pc-pvw { grid-area: pvw; } .pc-pgm { grid-area: pgm; } .pc-side { grid-area: side; }
.pc-shots { grid-area: shots; } .pc-sp { grid-area: sp; } .pc-audio { grid-area: audio; }
.pc-mon { position: relative; background: #000; border: 3px solid var(--sp-border, #444); border-radius: 6px;
  aspect-ratio: 16 / 9; overflow: hidden; }
.pc-mon img { width: 100%; height: 100%; object-fit: contain; display: block; }
.pc-mon.pvw { border-color: #2e8b57; } .pc-mon.pgm { border-color: #c0392b; }
.pc-mon .pc-tag { position: absolute; left: .4rem; top: .3rem; font-size: .75rem; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; padding: .1rem .45rem; border-radius: 4px; background: rgba(0,0,0,.65); }
.pc-mon.pgm .pc-tag { background: #c0392b; } .pc-mon.pvw .pc-tag { background: #2e8b57; }
.pc-mon .pc-by { position: absolute; right: .4rem; bottom: .3rem; font-size: .7rem; opacity: .8;
  background: rgba(0,0,0,.6); padding: .1rem .4rem; border-radius: 4px; }
.pc-shot { position: relative; width: 9.5rem; border: 3px solid var(--sp-border, #444); border-radius: 6px;
  background: var(--sp-surface-2, #222); cursor: pointer; padding: 0; overflow: hidden; text-align: left; }
.pc-shot img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; background: #000; }
.pc-shot .pc-shot-label { display: block; padding: .2rem .4rem; font-size: .8rem; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.pc-shot .pc-key { position: absolute; left: .3rem; top: .25rem; font-size: .7rem; background: rgba(0,0,0,.65);
  padding: 0 .35rem; border-radius: 3px; }
.pc-shot.armed { border-color: #2e8b57; } .pc-shot.live { border-color: #c0392b; }
.pc-shot.unbuilt { opacity: .45; cursor: not-allowed; }
.pc-take { font-size: 1.2rem; font-weight: 700; min-width: 8rem; }
.pc-meter { height: .45rem; background: #222; border-radius: 3px; overflow: hidden; }
.pc-meter > span { display: block; height: 100%; width: 0; background: linear-gradient(90deg, #2e8b57 70%, #c9a227 85%, #c0392b); }
.pc-strip { display: grid; grid-template-columns: 1fr auto; gap: .25rem .5rem; align-items: center; font-size: .85rem; }
.pc-scene { width: 8.5rem; text-align: left; border-left: .4rem solid transparent; }
.pc-scene.active { outline: 2px solid var(--ttrpg-accent, #c9a227); }
.pc-clock { font-variant-numeric: tabular-nums; font-size: 1.25rem; }
.pc-count.warn { color: #c9a227; } .pc-count.over { color: #c0392b; }
.pc-banner { background: #c0392b; color: #fff; padding: .35rem .6rem; border-radius: 4px; }
.pc-markers { max-height: 9rem; overflow: auto; font-size: .8rem; }
```

- [ ] **Step 5: Markup — `web/app/views/ttrpg/producer/template.js`**

```js
// Producer console markup. Everything dynamic is painted by console.js; this
// renders the frame once from the first state document.
import { html } from '../../../lib/dom.js';

const shotTile = (s, i) => html`<button type="button" class="pc-shot ${s.built ? '' : 'unbuilt'}" data-shot="${s.key}"
  title="${s.built ? 'Arm ' + s.label : s.label + ': scene not built — run Build on the Broadcast page'}">
  <img alt="" data-snap="${s.key}"><span class="pc-key">${i < 9 ? i + 1 : ''}</span>
  <span class="pc-shot-label">${s.label}</span></button>`;

export function render(d) {
  return html`<div class="pc" id="pc">
  <div class="pc-banner mb-1" id="pc-banner" hidden>OBS is not connected — shots, Take and the OBS audio strip are disabled.</div>
  <div class="pc-pvw"><div class="pc-mon pvw"><img alt="" id="pc-pvw-img"><span class="pc-tag">Preview</span>
    <span class="pc-by" id="pc-pvw-name">${d.preview || 'nothing armed'}</span></div></div>
  <div class="pc-pgm"><div class="pc-mon pgm"><img alt="" id="pc-pgm-img"><span class="pc-tag">Program &#9679; LIVE</span>
    <span class="pc-by" id="pc-pgm-name">${d.program}</span></div></div>

  <div class="pc-side ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1">
      <span><span class="badge ${d.streaming ? 'bg-danger' : 'bg-secondary'}" id="pc-stream-pill">STREAM</span>
        <span class="badge ${d.recording ? 'bg-danger' : 'bg-secondary'}" id="pc-rec-pill">REC</span></span>
      <span class="small" id="pc-consoles">${d.consoles} console${d.consoles === 1 ? '' : 's'}</span></div>
    <div class="pc-clock" id="pc-clock" title="Session clock (click to reset)">00:00:00</div>
    <div class="small text-secondary" id="pc-session">${d.session ? d.session.title : 'no active session'}</div>
    <div class="mt-2 d-flex align-items-center gap-1">
      <span class="pc-count" id="pc-count">--:--</span>
      <input type="number" class="form-control form-control-sm" id="pc-count-min" min="1" max="180" value="10" style="width:4.5rem" title="minutes">
      <button type="button" class="btn btn-sm btn-outline-secondary" id="pc-count-start">Start</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="pc-count-clear" title="clear">&times;</button></div>
    <div class="mt-2 d-flex gap-1">
      <input type="text" class="form-control form-control-sm" id="pc-marker-note" placeholder="marker note (K)">
      <button type="button" class="btn btn-sm btn-ttrpg" id="pc-marker">&#9873;</button></div>
    <div class="pc-markers mt-1" id="pc-markers"></div>
    <div class="form-check form-switch mt-2 small">
      <input class="form-check-input" type="checkbox" id="pc-autocam" ${d.auto_cam_paused ? '' : 'checked'}>
      <label class="form-check-label" for="pc-autocam">Let auto-cam run</label></div>
    <div class="mt-2 small text-secondary" id="pc-talkback-slot"></div>
  </div>

  <div class="pc-shots ttrpg-card p-2">
    <div class="d-flex flex-wrap gap-2 mb-2" id="pc-shot-row">${d.shots.map(shotTile)}</div>
    <div class="d-flex flex-wrap align-items-center gap-2">
      <button type="button" class="btn btn-danger pc-take" id="pc-take" title="Enter">TAKE &#9654;</button>
      <button type="button" class="btn btn-outline-danger pc-take" id="pc-auto" title="Space">AUTO &#10227;</button>
      <select class="form-select form-select-sm" id="pc-transition" style="width:auto">
        ${d.transitions.map(t => html`<option value="${t}" ${t === d.transition ? 'selected' : ''}>${t}</option>`)}</select>
      <input type="number" class="form-control form-control-sm" id="pc-ms" value="${d.transition_ms || 300}" min="0" max="5000" step="50" style="width:5.5rem" title="ms">
      <span class="small text-secondary ms-auto">1–9 arm &middot; Enter take &middot; Space auto &middot; M mute all &middot; K marker &middot; Esc clear</span>
    </div>
  </div>

  <div class="pc-sp ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1"><b>ScenePlay</b>
      <span class="small text-secondary" id="pc-nowplaying"></span></div>
    <div class="d-flex flex-wrap gap-1 mb-2" id="pc-scenes"></div>
    <div class="d-flex gap-1">
      <button type="button" class="btn btn-sm btn-outline-secondary" data-sp="/nextsong">Skip &#9197;</button>
      <button type="button" class="btn btn-sm btn-outline-danger" data-sp="/killqueue">Kill &#9209;</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-sp="/api/lights-off">Lights off</button>
      <input type="range" class="form-range ms-2" id="pc-vol" min="0" max="100" style="width:8rem" title="music volume"></div>
  </div>

  <div class="pc-audio ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1"><b>Audio</b>
      <button type="button" class="btn btn-sm btn-danger" id="pc-mute-all" title="M">MUTE ALL BUT DM</button></div>
    <div class="pc-strip" id="pc-strip"></div>
  </div>
</div>`;
}
```

- [ ] **Step 6: Behaviour — `web/app/views/ttrpg/producer/console.js`**

```js
// Producer console behaviour: arm / take / auto, snapshot polling, levels,
// audio strip, ScenePlay tiles, clocks, markers, hotkeys.
import { $, $$, html, render, esc } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { token } from '../../../auth.js';

const P = '/ttrpg/producer/api';
const snapUrl = (target) => `${P}/snap/${encodeURIComponent(target)}?token=${encodeURIComponent(token() || '')}&_=${Date.now()}`;

export function createConsole(ctx, root) {
  let state = null;          // last state document
  let scenes = [];           // ScenePlay scenes
  let sceneStates = {};      // scene_ID -> queued/active flags from the queue topic
  let rows = [];             // OBS audio rows (from /ttrpg/obs/api/state)
  const failures = { program: 0, preview: 0 };

  // ── painting ──
  function paintState(d) {
    state = d;
    $('#pc-banner', root).hidden = d.connected;
    const by = d.last_switch ? ({ producer: 'producer', broadcast: 'broadcast page' }[d.last_switch.by] || 'automatic') : '';
    $('#pc-pgm-name', root).textContent = (d.program || '') + (by ? ' · by ' + by : '');
    $('#pc-pvw-name', root).textContent = d.preview || 'nothing armed';
    $('#pc-stream-pill', root).className = 'badge ' + (d.streaming ? 'bg-danger' : 'bg-secondary');
    $('#pc-rec-pill', root).className = 'badge ' + (d.recording ? 'bg-danger' : 'bg-secondary');
    $('#pc-consoles', root).textContent = `${d.consoles} console${d.consoles === 1 ? '' : 's'}`;
    $('#pc-autocam', root).checked = !d.auto_cam_paused;
    for (const b of $$('.pc-shot', root)) {
      const s = d.shots.find(x => x.key === b.dataset.shot);
      b.classList.toggle('live', !!s && s.scene === d.program);
      b.classList.toggle('armed', !!s && s.scene === d.preview && s.scene !== d.program);
      b.classList.toggle('unbuilt', !!s && !s.built);
    }
    for (const el of $$('#pc-take, #pc-auto, .pc-shot, #pc-mute-all', root)) el.disabled = !d.connected;
    paintMarkers(d.markers || []);
  }

  function paintMarkers(ms) {
    render($('#pc-markers', root), html`${ms.slice().reverse().slice(0, 30).map(m =>
      html`<div>${m.at.slice(11)} ${m.timecode ? html`<code>${m.timecode.slice(0, 8)}</code>` : ''} ${m.note}${m.chapter ? ' ✓' : ''}</div>`)}`);
  }

  function paintScenes() {
    render($('#pc-scenes', root), html`${scenes.map(s => {
      const st = sceneStates[s.scene_ID] || {};
      return html`<button type="button" class="btn btn-sm btn-outline-secondary pc-scene ${st.active ? 'active' : ''}"
        data-scene="${s.scene_ID}" style="border-left-color:${esc(s.color || 'transparent')}" title="${s.modelName || ''} ${s.effectName || ''}">
        ${s.sceneName}</button>`; })}`);
  }

  function paintStrip() {
    render($('#pc-strip', root), html`${rows.map(r => html`
      <div class="d-flex align-items-center gap-2"><span style="width:7rem" class="text-truncate">${r.name}</span>
        <div class="pc-meter flex-grow-1" data-level="${r.source}"><span></span></div></div>
      <button type="button" class="btn btn-sm ${r.muted ? 'btn-danger' : 'btn-outline-secondary'}" data-mute="${r.character_id}" data-muted="${r.muted ? 1 : 0}">${r.muted ? 'Unmute' : 'M'}</button>`)}
      <div class="d-flex align-items-center gap-2"><span style="width:7rem">Music</span>
        <div class="pc-meter flex-grow-1" data-level="ScenePlay Music"><span></span></div></div><span></span>`);
  }

  function paintLevels(lv) {
    for (const m of $$('[data-level]', root)) {
      const peaks = lv[m.dataset.level] || [];
      const peak = peaks.length ? Math.max(...peaks) : 0;
      const db = peak > 0 ? 20 * Math.log10(peak) : -60;          // multiplier -> dBFS
      m.firstElementChild.style.width = Math.max(0, Math.min(100, (db + 60) / 60 * 100)) + '%';
    }
  }

  function tickClocks() {
    if (!state) return;
    const clock = $('#pc-clock', root);
    if (state.clock_start) {
      const s = Math.max(0, (Date.now() - Date.parse(state.clock_start.replace(' ', 'T'))) / 1000);
      clock.textContent = hms(s);
    }
    const c = $('#pc-count', root);
    if (state.countdown_until) {
      const left = (Date.parse(state.countdown_until.replace(' ', 'T')) - Date.now()) / 1000;
      c.textContent = (left < 0 ? '-' : '') + hms(Math.abs(left)).slice(3);
      c.className = 'pc-count' + (left < 0 ? ' over' : left < 60 ? ' warn' : '');
    } else { c.textContent = '--:--'; c.className = 'pc-count'; }
  }
  const hms = s => [3600, 60, 1].map((u, i) => String(Math.floor(s / u) % (i ? 60 : 100)).padStart(2, '0')).join(':');

  // ── snapshots ──
  function refreshSnap(img, target) {
    if (!state || !state.connected || document.hidden) return;
    const next = new Image();
    next.onload = () => { img.src = next.src; failures[target] = 0; };
    next.onerror = () => { failures[target] = (failures[target] || 0) + 1; };
    next.src = snapUrl(target);
  }
  function snapMonitors() {
    // three failures in a row: back off to 1 fps until one succeeds
    const slow = (failures.program >= 3 || failures.preview >= 3) && (Date.now() % 1000) > 500;
    if (slow) return;
    refreshSnap($('#pc-pgm-img', root), 'program');
    if (state && state.preview) refreshSnap($('#pc-pvw-img', root), 'preview');
  }
  function snapTiles() {
    for (const img of $$('[data-snap]', root)) refreshSnap(img, img.dataset.snap);
  }

  // ── actions ──
  async function arm(key) {
    const r = await api.post(`${P}/arm`, { key });
    if (!r.ok) toast.warn(r.error);
    else refreshSnap($('#pc-pvw-img', root), 'preview');
  }
  async function take(auto) {
    const body = auto ? { ms: Number($('#pc-ms', root).value) || 300 }
                      : { transition: $('#pc-transition', root).value, ms: Number($('#pc-ms', root).value) || 0 };
    const r = await api.post(`${P}/${auto ? 'auto' : 'take'}`, body);
    if (!r.ok) toast.warn(r.error);
  }
  async function marker() {
    const inp = $('#pc-marker-note', root);
    const r = await api.post(`${P}/marker`, { note: inp.value });
    inp.value = '';
    if (r.warning) toast.warn(r.warning); else toast.success(`Marker: ${r.marker.note}`);
  }
  async function muteAll() {
    await api.post('/ttrpg/obs/api/mute', { all: true, muted: true });
    toast.info('Players muted');
    loadRows();
  }
  async function loadRows() {
    try {
      const d = await api.get('/ttrpg/obs/api/state', { quiet: true });
      rows = (d.rows || []).map(r => ({ name: r.name || r.character_name || String(r.character_id), source: r.source_name || ((r.scene_name || '') + ' Cam'),
        character_id: r.character_id, muted: !!r.muted }));
      paintStrip();
    } catch (e) { /* OBS state is optional here */ }
  }
  async function loadScenes() {
    try { const d = await api.get('/api/scenes?length=500', { quiet: true }); scenes = d.data || []; paintScenes(); } catch (e) { scenes = []; }
  }

  // ── wiring ──
  function wire() {
    ctx.on(root, 'click', async (e) => {
      const shot = e.target.closest('.pc-shot'); if (shot && !shot.disabled && !shot.classList.contains('unbuilt')) return arm(shot.dataset.shot);
      const sc = e.target.closest('[data-scene]'); if (sc) { await api.post(`/activatescenes/?id=${sc.dataset.scene}`); return; }
      const sp = e.target.closest('[data-sp]'); if (sp) { await api.post(sp.dataset.sp); return; }
      const mu = e.target.closest('[data-mute]'); if (mu) { await api.post('/ttrpg/obs/api/mute', { character_id: Number(mu.dataset.mute), muted: mu.dataset.muted !== '1' }); return loadRows(); }
      switch (e.target.closest('button, .pc-clock') && (e.target.closest('button, .pc-clock').id)) {
        case 'pc-take': return take(false);
        case 'pc-auto': return take(true);
        case 'pc-marker': return marker();
        case 'pc-mute-all': return muteAll();
        case 'pc-count-start': return api.post(`${P}/countdown`, { seconds: 60 * (Number($('#pc-count-min', root).value) || 10) });
        case 'pc-count-clear': return api.post(`${P}/countdown`, { clear: true });
        case 'pc-clock': if (confirm('Reset the session clock?')) return api.post(`${P}/clock/reset`); return;
      }
    });
    ctx.on($('#pc-autocam', root), 'change', e => api.post(`${P}/auto-cam-pause`, { paused: !e.target.checked }));
    ctx.on($('#pc-transition', root), 'change', e => api.post(`${P}/transition`, { name: e.target.value, ms: Number($('#pc-ms', root).value) || 0 }));
    ctx.on($('#pc-vol', root), 'change', e => api.post('/set_volume', { volume: Number(e.target.value) }));   // same body the player bar sends — check `grep -n set_volume web/app/ui/player_bar.js` and copy its exact call
    ctx.on($('#pc-marker-note', root), 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); marker(); } });
    ctx.on(document, 'keydown', e => {
      const t = e.target; if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (/^[1-9]$/.test(e.key)) { const s = $$('.pc-shot', root)[Number(e.key) - 1]; if (s && !s.classList.contains('unbuilt')) arm(s.dataset.shot); e.preventDefault(); }
      else if (e.key === 'Enter') { take(false); e.preventDefault(); }
      else if (e.key === ' ') { take(true); e.preventDefault(); }
      else if (e.key === 'm' || e.key === 'M') { muteAll(); e.preventDefault(); }
      else if (e.key === 'k' || e.key === 'K') { marker(); e.preventDefault(); }
      else if (e.key === 'Escape') { api.post(`${P}/arm`, { key: '' }).catch(() => {}); }
    });
  }

  return {
    paintState, paintScenes, paintStrip, paintLevels, tickClocks, snapMonitors, snapTiles, loadRows, loadScenes, wire,
    setSceneStates(s) { sceneStates = s || {}; paintScenes(); },
    setNowPlaying(np) { $('#pc-nowplaying', root).textContent = np && np.title ? `♪ ${np.title}` : ''; if (np && np.volume != null) $('#pc-vol', root).value = np.volume; },
  };
}
```

The Escape handler posts an empty key, which the server answers with a 400 `bad_shot`; the `.catch` swallows it and the preview simply stays. (Clearing Preview in OBS Studio Mode has no request; the armed marker is cleared on the next Take.)

`/ttrpg/obs/api/state` row keys: run `.venv/bin/python -c "import routers.obs as o, inspect; print(inspect.getsource(o.api_state))"` and adjust the four field names in `loadRows()` (`name`, `source_name`, `character_id`, `muted`) to what the rows actually carry — the strip must show one line per on-stream character with their tile's cam source name as the meter key (the OBS input name is `<scene name> Cam`, see `_source_name_for`).

- [ ] **Step 7: Mount — `web/app/views/ttrpg/producer/index.js`**

```js
// Producer console (/ttrpg/producer): a second person runs the stream from
// their own laptop. Spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md
import { render } from '../../../lib/dom.js';
import { loadCss } from '../../../lib/loader.js';
import { api } from '../../../api.js';
import { sse } from '../../../sse.js';
import { store } from '../../../store.js';
import { render as tpl } from './template.js';
import { createConsole } from './console.js';

export const title = 'Producer console';

const P = '/ttrpg/producer/api';
let consoleId = null;
const offs = [];

export async function mount(outlet, ctx) {
  await loadCss('/css/views/producer.css');
  const d = await api.get(`${P}/state`);
  render(outlet, tpl(d));
  const c = createConsole(ctx, outlet);
  c.paintState(d);
  c.wire();
  const opened = await api.post(`${P}/session`);
  consoleId = opened.console_id;

  const refresh = async () => { try { c.paintState(await api.get(`${P}/state`, { quiet: true })); } catch (e) {} };
  offs.push(sse.subscribe('producer', refresh, { fallback: { every: 5000, fetch: refresh } }));
  offs.push(sse.subscribe('obs', refresh));
  offs.push(sse.subscribe('queue', q => c.setSceneStates(q && q.scene_states), { fallback: { every: 5000, fetch: () => api.get('/api/scenes/queue-states', { quiet: true }) } }));
  offs.push(store.subscribe('nowPlaying', np => c.setNowPlaying(np), { immediate: true }));

  await Promise.all([c.loadScenes(), c.loadRows()]);
  ctx.every(500, () => c.snapMonitors());
  ctx.every(3000, () => c.snapTiles());
  ctx.every(250, async () => { if (document.hidden) return; try { const l = await api.get(`${P}/levels`, { quiet: true }); c.paintLevels(l.levels || {}); } catch (e) {} });
  ctx.every(1000, () => c.tickClocks());
  ctx.every(15000, () => api.post(`${P}/session/ping`, { console_id: consoleId }).catch(() => {}));
  c.snapMonitors(); c.snapTiles(); c.tickClocks();
}

export function unmount() {
  for (const off of offs.splice(0)) { try { off(); } catch (e) {} }
  if (consoleId) { api.del(`${P}/session/${consoleId}`).catch(() => {}); consoleId = null; }
}
```

A tab closed without `unmount` (crash, power off) simply stops pinging; the server reaps it after `PING_TTL_S` and drops Studio Mode after the grace. No `sendBeacon` close: beacons cannot carry the bearer token.

Check that `/api/scenes/queue-states` exists (`grep -rn "queue-states" routers/`); if the path differs, use the one the home view uses (`grep -n "queue-states\|scene_states" web/app/views/media/home.js`).

- [ ] **Step 8: Broadcast page link and page data**

In `routers/obs/__init__.py`, inside the `broadcast` page-data function's returned `cfg` dict (the one that has `'music_push': music_push_url(),` near line 183) add:

```python
        'producer_url':  '/ttrpg/producer',
```

In `web/app/views/ttrpg/obs_broadcast/template.js`, change line ~657

```js
      <h4 style="${H6}" class="mb-0">&#127909; Broadcast (OBS)</h4>
```

to

```js
      <h4 style="${H6}" class="mb-0">&#127909; Broadcast (OBS)
        <a href="${cfg.producer_url}" class="btn btn-sm btn-outline-secondary ms-2" title="Preview/Program switching, multiview, audio strip">&#127916; Producer console</a></h4>
```

(`cfg` is already in scope in that template — it renders `cfg.music_push` further down. If the header is rendered in a function that does not receive `cfg`, use the literal `/ttrpg/producer` instead.)

- [ ] **Step 9: Syntax check, tests, manual walk**

```bash
for f in web/app/views/ttrpg/producer/*.js; do node --check "$f" || exit 1; done
.venv/bin/python -m pytest tests/test_web_assets.py tests/test_obs_overlays.py -q -p no:warnings
```

Expected: all PASS. Then start a scratch server and walk the page:

```bash
SP_PORT=8091 SP_WORKERS=0 SP_INTEGRATIONS=0 SP_DB_PATH=/tmp/producer-dev.db .venv/bin/python ws.py &   # first run creates an empty DB; set up a DM at /ttrpg/setup
.venv/bin/python scripts/spa_smoke.py http://127.0.0.1:8091 <dm> <pw> /ttrpg/producer
```

Expected: the smoke reports no console errors on `/ttrpg/producer`; the page shows the red "OBS is not connected" banner (integrations are off), disabled shots, the ScenePlay tiles and the clocks ticking.

- [ ] **Step 10: Commit**

```bash
git add web/app/routes.js web/app/views/ttrpg/producer web/css/views/producer.css web/app/views/ttrpg/obs_broadcast/template.js routers/obs/__init__.py tests/test_web_assets.py
git commit -m "producer console page: preview/program, multiview, strip, ScenePlay tiles, clocks, markers, hotkeys

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Smoke path, docs, full check

**Files:**
- Modify: `scripts/spa_smoke.py:12`, `CLAUDE.md` (Routers section), `README.md` (OBS / Broadcast section), `docs/SPA_PARITY.md` (one line)

- [ ] **Step 1: Smoke default path**

Change `scripts/spa_smoke.py` line 12 to

```python
paths = sys.argv[4:] or ['/ttrpg', '/', '/scenes', '/ttrpg/change-password', '/ttrpg/producer', '/nope']
```

- [ ] **Step 2: Docs**

`CLAUDE.md`, in the "Routers" paragraph, append one sentence:

```
`routers/producer.py` is the producer console API (`/ttrpg/producer/api/*`, DM-gated): OBS Studio Mode
preview/program switching, snapshot multiview, markers, countdown; it reuses the OBS router's scene naming and
party order and never adds OBS sources (design: docs/superpowers/specs/2026-09-14-producer-console-core-design.md).
```

`README.md`: find the Broadcast / OBS feature paragraph (`grep -n "Broadcast" README.md | head -3`) and add after it:

```
**Producer console** (`/ttrpg/producer`, DM login): a second person on their own laptop can run the stream —
arm a shot in Preview, Take or Auto it to Program (OBS Studio Mode), watch snapshot thumbnails of Program,
Preview and every player, mute feeds, fire ScenePlay scenes, keep a session clock and break countdown, and drop
chapter markers into the recording. Hotkeys: 1–9 arm, Enter take, Space auto, M mute all, K marker.
```

`docs/SPA_PARITY.md`: add a row `| /ttrpg/producer | new in 2.1 (no 1.x template) | done |` in the same table format as the existing rows.

- [ ] **Step 3: Full check**

```bash
.venv/bin/ruff check . && .venv/bin/python -m pytest tests -q -p no:warnings
```

Expected: ruff clean, every test passes.

- [ ] **Step 4: Commit**

```bash
git add scripts/spa_smoke.py CLAUDE.md README.md docs/SPA_PARITY.md
git commit -m "producer console: smoke path and docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Manual acceptance on the appliance (after Task 9, by Eric)

1. Restart the appliance (`pkill -f 'ScenePlay/[w]s.py'` then `~/ScenePlay/startApp.sh`, or press F5).
2. On a second laptop, log in as a DM and open `http://10.0.4.33:8086/ttrpg/producer`.
3. OBS should flip into Studio Mode within a second; the Program thumbnail matches OBS's program.
4. Press `3` (a player) then `Enter`: OBS cuts; press `1` then `Space`: fade to the party scene.
5. Click a ScenePlay scene tile: music and LEDs change; the tile outlines as active.
6. Start recording in OBS, press `K` with a note: OBS shows a chapter in the recording (MKV/hybrid MP4) and the marker list shows the entry.
7. Close the console tab; after ~10 s OBS leaves Studio Mode and auto-cam resumes if it was on.

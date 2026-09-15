// Producer console behaviour: arm / take / auto, snapshot polling, levels,
// audio strip, ScenePlay tiles, clocks, markers, hotkeys.
import { $, $$, html, render } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { token } from '../../../auth.js';

const P = '/ttrpg/producer/api';
const snapUrl = (target) => `${P}/snap/${encodeURIComponent(target)}?token=${encodeURIComponent(token() || '')}&_=${Date.now()}`;

export function createConsole(ctx, root) {
  let state = null;          // last state document
  let scenes = [];           // ScenePlay scene tiles (/api/scenes + /api/v1/home)
  let sceneStates = {};      // scene_ID -> 'all'|'some'|'none' from the queue topic
  let activeScene = null;    // {id, name} of the scene ScenePlay is playing
  let rows = [];             // OBS audio rows (from /ttrpg/obs/api/state)
  let shotSig = '';          // signature of state.shots' (character_id, scene) pairs, to
                              // notice when the strip's per-row meter key needs recomputing
  const failures = { program: 0, preview: 0 };
  const inflight = {};       // per snapshot target: a frame is still loading
  let stateAt = 0;           // performance.now() when `state` was fetched

  // ── painting ──
  function paintState(d) {
    state = d;
    stateAt = performance.now();
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
    // The strip's meter key is each player's per-character cam scene, which
    // lives on state.shots (not on the OBS row, which only has the shared
    // party scene) — repaint the strip when that mapping actually changes.
    const sig = JSON.stringify(d.shots.map(s => [s.character_id, s.scene]));
    if (sig !== shotSig) { shotSig = sig; if (rows.length) paintStrip(); }
    paintMarkers(d.markers || []);
  }

  function paintMarkers(ms) {
    render($('#pc-markers', root), html`${ms.slice().reverse().slice(0, 30).map(m =>
      html`<div>${m.at.slice(11)} ${m.timecode ? html`<code>${m.timecode.slice(0, 8)}</code>` : ''} ${m.note}${m.chapter ? ' ✓' : ''}</div>`)}`);
  }

  function paintScenes() {
    const activeId = activeScene ? activeScene.id : null;
    const named = scenes.find(s => s.scene_ID === activeId);
    $('#pc-active-scene', root).textContent =
      activeScene ? 'active: ' + (named ? named.sceneName : activeScene.name) : 'no scene active';
    render($('#pc-scenes', root), html`${scenes.map(s => {
      // queue topic first (live), then whatever /api/v1/home said at load.
      const q = sceneStates[s.scene_ID] !== undefined ? sceneStates[s.scene_ID] : (s.queued || '');
      const cls = 'btn btn-sm btn-outline-secondary pc-scene'
        + (s.scene_ID === activeId ? ' active' : '')
        + (q === 'all' || q === 'some' ? ' queued' : '');
      const tip = [s.modelName, s.effectName].filter(Boolean).join(' \u00b7 ');
      return html`<button type="button" class="${cls}" data-scene="${s.scene_ID}"
        style="border-left-color:${s.color ? 'rgb(' + s.color + ')' : 'transparent'}" title="${tip}">
        ${s.sceneName}</button>`; })}`);
  }

  function paintStrip() {
    // The OBS row only knows the shared party scene; the per-character cam
    // source (what obs_ws.levels() is actually keyed by) lives on this
    // console's own state.shots, keyed by character_id.
    render($('#pc-strip', root), html`${rows.map(r => {
      const shot = state && (state.shots || []).find(s => s.character_id === r.character_id);
      const source = shot ? shot.scene + ' Cam' : '';
      return html`
      <div class="d-flex align-items-center gap-2"><span style="width:7rem" class="text-truncate">${r.name}</span>
        <div class="pc-meter flex-grow-1" data-level="${source}"><span></span></div></div>
      <button type="button" class="btn btn-sm ${r.muted ? 'btn-danger' : 'btn-outline-secondary'}" data-mute="${r.character_id}" data-muted="${r.muted ? 1 : 0}">${r.muted ? 'Unmute' : 'M'}</button>`; })}
      <div class="d-flex align-items-center gap-2"><span style="width:7rem">Music</span>
        <div class="pc-meter flex-grow-1" data-level="ScenePlay Music|ScenePlay Music Feed"><span></span></div></div><span></span>`);
  }

  function paintLevels(lv) {
    for (const m of $$('[data-level]', root)) {
      // one meter may watch several OBS inputs (the music bed is captured
      // under either name depending on how the scene was built) — loudest wins
      const peaks = m.dataset.level.split('|').flatMap(k => lv[k] || []);
      const peak = peaks.length ? Math.max(...peaks) : 0;
      const db = peak > 0 ? 20 * Math.log10(peak) : -60;          // multiplier -> dBFS
      m.firstElementChild.style.width = Math.max(0, Math.min(100, (db + 60) / 60 * 100)) + '%';
    }
  }

  function tickClocks() {
    // Both clocks are resolved server-side (the stored strings are the
    // server's local time with no offset — a laptop in another timezone, or
    // with a skewed clock, cannot parse them). All this does is add the time
    // that has passed since the document arrived.
    if (!state) return;
    const since = Math.max(0, (performance.now() - stateAt) / 1000);
    const clock = $('#pc-clock', root);
    if (state.clock_elapsed_s !== null && state.clock_elapsed_s !== undefined) {
      clock.textContent = hms(state.clock_elapsed_s + since);
    }
    const c = $('#pc-count', root);
    if (state.countdown_left_s !== null && state.countdown_left_s !== undefined) {
      const left = state.countdown_left_s - since;
      c.textContent = (left < 0 ? '-' : '') + countdown(Math.abs(left));
      c.className = 'pc-count' + (left < 0 ? ' over' : left < 60 ? ' warn' : '');
    } else { c.textContent = '--:--'; c.className = 'pc-count'; }
  }
  const hms = s => [3600, 60, 1].map((u, i) => String(Math.floor(s / u) % (i ? 60 : 100)).padStart(2, '0')).join(':');
  // MM:SS for the usual break, H:MM:SS once an hour is on the clock
  const countdown = s => (s >= 3600 ? hms(s).replace(/^0/, '') : hms(s).slice(3));

  // ── snapshots ──
  function refreshSnap(img, target) {
    if (!state || !state.connected || document.hidden) return;
    // A slow OBS (or a big tile) must not queue frames behind itself: skip
    // the tick while this target's last request is still loading.
    if (inflight[target]) return;
    inflight[target] = true;
    const next = new Image();
    next.onload = () => { inflight[target] = false; img.src = next.src; failures[target] = 0; };
    next.onerror = () => { inflight[target] = false; failures[target] = (failures[target] || 0) + 1; };
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
      // source (the meter key) is resolved in paintStrip() from state.shots,
      // not from this row's r.scene — that's the shared party scene, not the
      // per-character cam OBS actually meters.
      rows = (d.rows || []).filter(r => r.on_stream).map(r => ({
        name: r.name, character_id: r.character_id, muted: !!r.muted,
      }));
      paintStrip();
    } catch (e) { /* OBS state is optional here */ }
  }
  async function loadScenes() {
    // /api/scenes has every scene with its full name and the active flag;
    // /api/v1/home decorates the ones that have media or lights (colour, LED
    // pattern, WLED effect, queue state) but truncates the name to 15 chars.
    const [rows, decorated] = await Promise.all([
      api.get('/api/scenes?length=500', { quiet: true }).then(d => d.data || []).catch(() => []),
      api.get('/api/v1/home', { quiet: true }).then(d => d.scenes || []).catch(() => []),
    ]);
    const deco = new Map(decorated.map(s => [s.scene_ID, s]));
    const base = rows.length ? rows.filter(s => s.active) : decorated;
    scenes = base
      .slice()
      .sort((a, b) => (a.orderBy || a.orderby || 0) - (b.orderBy || b.orderby || 0))
      .map(s => ({ ...s, ...(deco.get(s.scene_ID) || {}), sceneName: s.sceneName }));
    paintScenes();
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
    ctx.on($('#pc-vol', root), 'change', e => api.post('/set_volume', { volume: Number(e.target.value) }));
    ctx.on($('#pc-marker-note', root), 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); marker(); } });
    ctx.on(document, 'keydown', e => {
      const t = e.target; if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // Marker and Escape stay live even while OBS is disconnected: a marker
      // is just a stored row, and Escape's arm-nothing no-op needs no OBS call.
      if (e.key === 'k' || e.key === 'K') { marker(); e.preventDefault(); return; }
      // Escape arms nothing: the server forgets the armed shot and leaves
      // OBS's preview alone (it is still what the next Take would put up).
      if (e.key === 'Escape') { api.post(`${P}/arm`, { key: '' }, { quiet: true }).catch(() => {}); return; }
      if (!state || !state.connected) return;   // same OBS-backed gate the mouse controls respect
      if (/^[1-9]$/.test(e.key)) { const s = $$('.pc-shot', root)[Number(e.key) - 1]; if (s && !s.disabled && !s.classList.contains('unbuilt')) arm(s.dataset.shot); e.preventDefault(); }
      else if (e.key === 'Enter') { take(false); e.preventDefault(); }
      else if (e.key === ' ') { take(true); e.preventDefault(); }
      else if (e.key === 'm' || e.key === 'M') { muteAll(); e.preventDefault(); }
    });
  }

  return {
    paintState, paintScenes, paintStrip, paintLevels, tickClocks, snapMonitors, snapTiles, loadRows, loadScenes, wire,
    setSceneStates(s) { sceneStates = s || {}; paintScenes(); },
    setNowPlaying(np) {
      // /api/nowplaying (and its SSE topic) carries the active scene as well
      // as the track — that is the only place the console can learn it.
      $('#pc-nowplaying', root).textContent = np && np.song ? `♪ ${np.song.name}` : '';
      activeScene = (np && np.scene) || null;
      paintScenes();
    },
    setVolume(v) { if (v != null) $('#pc-vol', root).value = v; },
  };
}

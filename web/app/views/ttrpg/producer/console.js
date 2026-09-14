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
      rows = (d.rows || []).filter(r => r.on_stream).map(r => ({
        name: r.name, source: r.scene + ' Cam', character_id: r.character_id, muted: !!r.muted,
      }));
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
    ctx.on($('#pc-vol', root), 'change', e => api.post('/set_volume', { volume: Number(e.target.value) }));
    ctx.on($('#pc-marker-note', root), 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); marker(); } });
    ctx.on(document, 'keydown', e => {
      const t = e.target; if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (/^[1-9]$/.test(e.key)) { const s = $$('.pc-shot', root)[Number(e.key) - 1]; if (s && !s.classList.contains('unbuilt')) arm(s.dataset.shot); e.preventDefault(); }
      else if (e.key === 'Enter') { take(false); e.preventDefault(); }
      else if (e.key === ' ') { take(true); e.preventDefault(); }
      else if (e.key === 'm' || e.key === 'M') { muteAll(); e.preventDefault(); }
      else if (e.key === 'k' || e.key === 'K') { marker(); e.preventDefault(); }
      // Escape arms nothing: the server answers 400 bad_shot, and quiet:true
      // keeps that expected rejection from toasting — the preview simply stays.
      else if (e.key === 'Escape') { api.post(`${P}/arm`, { key: '' }, { quiet: true }).catch(() => {}); }
    });
  }

  return {
    paintState, paintScenes, paintStrip, paintLevels, tickClocks, snapMonitors, snapTiles, loadRows, loadScenes, wire,
    setSceneStates(s) { sceneStates = s || {}; paintScenes(); },
    setNowPlaying(np) { $('#pc-nowplaying', root).textContent = np && np.song ? `♪ ${np.song.name}` : ''; },
    setVolume(v) { if (v != null) $('#pc-vol', root).value = v; },
  };
}

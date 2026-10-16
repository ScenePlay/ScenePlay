// Producer console behaviour: arm / take / map view, snapshot polling, levels,
// audio strip, ScenePlay tiles, clocks, markers, hotkeys.
import { $, $$, html, raw, render } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { token } from '../../../auth.js';
import { mapModeLabel } from './template.js';

const P = '/ttrpg/producer/api';
const snapUrl = (target) => `${P}/snap/${encodeURIComponent(target)}?token=${encodeURIComponent(token() || '')}&_=${Date.now()}`;

export function createConsole(ctx, root, onRefresh = null) {
  let state = null;          // last state document
  let scenes = [];           // ScenePlay scene tiles (/api/scenes + /api/v1/home)
  let sceneStates = {};      // scene_ID -> 'all'|'some'|'none' from the queue topic
  let activeScene = null;    // {id, name} of the scene ScenePlay is playing
  let rows = [];             // OBS audio rows (from /ttrpg/obs/api/state)
  let musicDb = 0;                // the music bed's OBS fader, dB
  let faderBusy = false, stripDirty = false;   // a drag in progress holds strip repaints
  const FADER_MIN = -30, FADER_MAX = 10, FADER_EVERY_MS = 120;   // FADER_MIN/MAX mirror routers.obs.VOLUME_DB_*
  let shotSig = '';          // signature of state.shots' (character_id, scene) pairs, to
                              // notice when the strip's per-row meter key needs recomputing
  const failures = { program: 0, preview: 0 };
  const inflight = {};       // per snapshot target: a frame is still loading
  let stateAt = 0;           // performance.now() when `state` was fetched

  // ── painting ──
  function paintState(d) {
    state = d;
    stateAt = performance.now();
    const upd = $('#pc-updated', root); if (upd) upd.textContent = 'updated ' + new Date().toLocaleTimeString() + (d.connected ? ' · OBS connected' : ' · OBS not connected');
    $('#pc-banner', root).hidden = d.connected;
    // The OBS button is a status light first, a control second: green while
    // connected (click = reconnect), red otherwise (click = connect).
    const ob = $('#pc-obs-connect', root);
    if (ob) {
      const o = d.obs || {};
      const busy = !d.connected && ['connecting', 'identifying', 'reconnecting'].includes(o.state);
      ob.className = 'btn btn-sm text-nowrap ' + (d.connected ? 'btn-success' : busy ? 'btn-warning' : 'btn-danger');
      ob.innerHTML = d.connected ? 'OBS &#10003; connected' : busy ? 'OBS &hellip; connecting' : (o.enabled ? 'OBS &#10007; reconnect' : 'OBS &#10007; connect');
      ob.title = d.connected ? `Connected to OBS at ${o.target || ''} — click to reconnect` : busy ? `Connecting to OBS at ${o.target || ''}` : `Not connected — click to ${o.enabled ? 'reconnect' : 'switch OBS control on and connect'}`;
    }
    if (!d.connected) {
      const o = d.obs || {};
      const text = !o.enabled ? `OBS control is switched off — nothing reaches ${o.target || 'OBS'} until it is on.`
        : o.state === 'connecting' || o.state === 'identifying' || o.state === 'reconnecting' ? `Connecting to OBS at ${o.target}…${o.error ? ' (last error: ' + o.error + ')' : ''}`
        : o.state === 'auth_failed' ? `OBS at ${o.target} refused the password — fix it on the Broadcast page, then reconnect.`
        : o.state === 'unsupported' ? `OBS at ${o.target} runs an obs-websocket this app cannot drive (needs v5).`
        : `OBS is not connected (${o.state || 'unknown'})${o.error ? ': ' + o.error : ''}.`;
      $('#pc-banner-text', root).textContent = text + ' Shots, Take and the OBS audio strip are disabled. Use the OBS button on the right to connect.';
    }
    const by = d.last_switch ? ({ producer: 'producer', broadcast: 'broadcast page' }[d.last_switch.by] || 'automatic') : '';
    $('#pc-pgm-name', root).textContent = (d.program || '') + (by ? ' · by ' + by : '');
    $('#pc-pvw-name', root).textContent = d.preview || 'nothing armed';
    $('#pc-stream-pill', root).className = 'badge ' + (d.streaming ? 'bg-danger' : 'bg-secondary');
    $('#pc-rec-pill', root).className = 'badge ' + (d.recording ? 'bg-danger' : 'bg-secondary');
    $('#pc-consoles', root).textContent = `${d.consoles} console${d.consoles === 1 ? '' : 's'}`;
    $('#pc-autocam', root).checked = !d.auto_cam_paused;
    paintProducer(d.producer);
    const st = $('#pc-stale', root); if (st) { st.hidden = !d.stale_tiles; st.textContent = d.stale_tiles ? `${d.stale_tiles} tile${d.stale_tiles === 1 ? '' : 's'} render at an old size (the grid changed size) — Rebuild at a break; it reloads every camera.` : ''; }
    // The Take button says what it will do: the fade is the Broadcast page's.
    const fade = $('#pc-take-fade', root); if (fade) fade.textContent = (d.transition || 'Cut') + (d.transition_ms && !d.transition_fixed ? ' ' + d.transition_ms + 'ms' : '');
    paintMapMode(d.map_mode);
    paintFade(d);
    for (const b of $$('.pc-shot', root)) {
      const s = d.shots.find(x => x.key === b.dataset.shot);
      b.classList.toggle('live', !!s && s.scene === d.program);
      b.classList.toggle('armed', !!s && s.scene === d.preview && s.scene !== d.program);
      b.classList.toggle('unbuilt', !!s && !s.built);
    }
    for (const b of $$('.pc-shot', root)) {
      const s = d.shots.find(x => x.key === b.dataset.shot);
      b.classList.toggle('featured', !!s && s.character_id != null && s.character_id === d.featured_id);
      // The Party tile's reset badge lights while the grid is in its even layout.
      const rs = b.querySelector('.pc-reset'); if (rs) rs.classList.toggle('on', d.featured_id == null);
    }
    const scenesSig = JSON.stringify(d.scenes || []);
    if (scenesSig !== lastScenesSig) { lastScenesSig = scenesSig; loadScenes(); }
    const linksSig = JSON.stringify([d.scene_links, d.scene_links_live]);
    if (linksSig !== JSON.stringify([sceneLinks, sceneLinksLive])) { sceneLinks = d.scene_links || {}; sceneLinksLive = !!d.scene_links_live; paintScenes(); }
    const note = $('#pc-closeups-note', root);
    if (note) note.hidden = !d.connected || !d.shots.some(s => s.kind !== 'special' && !s.built);
    for (const el of $$('#pc-take, .pc-shot, #pc-mute-all, #pc-mute-everyone, #pc-unmute-all, #pc-rebuild', root)) el.disabled = !d.connected;
    // The strip's meter key is each player's per-character cam scene, which
    // lives on state.shots (not on the OBS row, which only has the shared
    // party scene) — repaint the strip when that mapping actually changes.
    const sig = JSON.stringify(d.shots.map(s => [s.character_id, s.scene]));
    if (sig !== shotSig) { shotSig = sig; if (rows.length) paintStrip(); }
    paintMarkers(d.markers || []);
  }

  function paintProducer(p) {
    if (!p) return;
    const b = $('#pc-barge', root); if (!b) return;
    b.className = 'btn btn-sm ' + (p.on_screen ? 'btn-warning' : 'btn-outline-warning');
    b.textContent = p.on_screen ? 'Leave grid' : 'Barge in';
    const cam = $('#pc-producer-cam', root); if (cam && p.push_url) cam.href = p.push_url;
    const feed = $('#pc-producer-feed', root);
    if (feed) feed.textContent = p.feed === 'live' ? 'camera live' : p.feed === 'stale' ? 'camera dropped' : '';
    const name = $('#pc-producer-name', root);
    if (name && document.activeElement !== name) name.value = p.name || 'Producer';
    const ic = $('#pc-producer-icon', root);
    if (ic && document.activeElement !== ic && ic.value !== (p.icon || '')) ic.value = p.icon || '';
  }

  // The Take fade: type and length, saved on the server (obs_transition /
  // obs_transition_ms) so the Broadcast page and every Take agree.
  // Options carry a real `selected` attribute: dom.js's html`` is a string
  // template, so lit's boolean-attribute form (a `?` before `selected`) rendered as a bogus attribute the
  // browser ignores — both selects snapped to their first entry on every
  // repaint, and a Fade picked while the length box showed "Cut" saved 0 ms.
  const FADE_MS = [250, 500, 750, 1000, 1500, 2000];
  function paintFade(d) {
    const type = $('#pc-fade-type', root), ms = $('#pc-fade-ms', root);
    if (!type || !ms) return;
    const names = d.transitions || [];
    const fixed = new Set(d.transitions_fixed || []);
    const cur = d.transition || '';
    const isFixed = !!d.transition_fixed || fixed.has(cur);
    if (document.activeElement !== type) {
      const opts = names.length ? names : (cur ? [cur] : []);
      render(type, html`${opts.map(n => html`<option value="${n}"${n === cur ? raw(' selected') : ''}>${n}</option>`)}`);
      type.disabled = !names.length;
    }
    if (document.activeElement !== ms) {
      // The saved length, kept while Cut is selected so switching back to
      // Fade brings it along; a length outside the list is still offered.
      const curMs = Number(d.transition_ms) || 0;
      const list = curMs > 0 && !FADE_MS.includes(curMs) ? [...FADE_MS, curMs].sort((a, b) => a - b) : FADE_MS;
      render(ms, html`${list.map(v => html`<option value="${v}"${v === curMs ? raw(' selected') : ''}>${v} ms</option>`)}`);
      ms.disabled = isFixed;                                   // Cut: greyed, length remembered
    }
  }
  async function setFade() {
    const r = await api.post(`${P}/transition`, { name: $('#pc-fade-type', root).value, ms: Number($('#pc-fade-ms', root).value) }, { quiet: true }).catch(e => ({ ok: false, error: e.message }));
    if (!r.ok) toast.warn(r.error || 'Could not save the transition');
  }

  function paintMarkers(ms) {
    render($('#pc-markers', root), html`${ms.slice().reverse().slice(0, 30).map(m =>
      html`<div>${m.at.slice(11)} ${m.timecode ? html`<code>${m.timecode.slice(0, 8)}</code>` : ''} ${m.note}${m.chapter ? ' ✓' : ''}</div>`)}`);
  }

  let sceneLinks = {}, sceneLinksLive = false, lastScenesSig = null;
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
        ${s.sceneName}${sceneLinks[s.scene_ID] ? html`<span class="pc-link ${sceneLinksLive ? '' : 'off'}" title="${sceneLinksLive ? 'Activating this scene also cuts OBS to ' + sceneLinks[s.scene_ID] : 'Linked to ' + sceneLinks[s.scene_ID] + ' — scene link is switched off on the Broadcast page'}">&rarr; ${sceneLinks[s.scene_ID]}</span>` : ''}</button>`; })}`);
  }

  // One OBS fader per row, in dB. The value is the server's (persisted like
  // the mutes, re-asserted by every build), so what this slider shows is what
  // the OBS mixer shows.
  const fmtDb = db => (db > 0 ? '+' : '') + Math.round(db) + ' dB';
  const fader = (key, db) => html`<input type="range" class="form-range pc-fader" data-fader="${key}" min="${FADER_MIN}" max="${FADER_MAX}" step="1" value="${Math.round(db)}"
      title="Level on the stream (double-click: 0 dB)"><span class="pc-db" data-db-for="${key}">${fmtDb(db)}</span>`;
  function paintStrip() {
    // A refresh mid-drag would replace the slider under the pointer; hold the
    // repaint until the hand lets go.
    if (faderBusy) { stripDirty = true; return; }
    stripDirty = false;
    // The OBS row only knows the shared party scene; the per-character cam
    // source (what obs_ws.levels() is actually keyed by) lives on this
    // console's own state.shots, keyed by character_id.
    render($('#pc-strip', root), html`${rows.map(r => {
      const shot = state && (state.shots || []).find(s => s.character_id === r.character_id);
      const source = shot ? shot.scene + ' Cam' : '';
      return html`
      <div class="d-flex align-items-center gap-2"><span style="width:7rem" class="text-truncate">${r.name}</span>
        <div class="pc-meter flex-grow-1" data-level="${source}"><span></span></div>${fader(r.character_id, r.volume_db)}</div>
      <button type="button" class="btn btn-sm ${r.muted ? 'btn-danger' : 'btn-outline-secondary'}" data-mute="${r.character_id}" data-muted="${r.muted ? 1 : 0}">${r.muted ? 'Unmute' : 'M'}</button>`; })}
      <div class="d-flex align-items-center gap-2"><span style="width:7rem">Music</span>
        <div class="pc-meter flex-grow-1" data-level="ScenePlay Music|ScenePlay Music Feed"><span></span></div>${fader('music', musicDb)}</div><span></span>`);
  }
  // Faders post while dragging, at most every FADER_EVERY_MS per fader, then
  // once more on release so the final position always lands.
  const faderTimers = {};
  function postFader(key, db, now) {
    const body = key === 'music' ? { target: 'music', db } : { character_id: Number(key), db };
    const send = async () => {
      const r = await api.post('/ttrpg/obs/api/volume', body, { quiet: true }).catch(() => null);
      if (r && !r.ok) toast.warn(r.error);
    };
    if (now) { clearTimeout(faderTimers[key]); delete faderTimers[key]; return send(); }
    if (faderTimers[key]) return;
    faderTimers[key] = setTimeout(() => { delete faderTimers[key]; send(); }, FADER_EVERY_MS);
  }
  function setFader(el, db, now) {
    el.value = db;
    const lab = $(`[data-db-for="${el.dataset.fader}"]`, root); if (lab) lab.textContent = fmtDb(db);
    if (el.dataset.fader === 'music') musicDb = db;
    else { const r = rows.find(x => String(x.character_id) === el.dataset.fader); if (r) r.volume_db = db; }
    postFader(el.dataset.fader, db, now);
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
  // An empty body: the server applies the Broadcast page's transition and
  // duration, the one place the fade is set.
  async function take() {
    const r = await api.post(`${P}/take`, {});
    if (!r.ok) toast.warn(r.error);
  }
  // The battle map's AUTO / 2D / 3D button: the server steps the mode, so it
  // stays right even when the last change came from the map or the Broadcast
  // page. A setting, not an OBS call, so it works while OBS is disconnected.
  async function mapMode() {
    const r = await api.post('/ttrpg/obs/api/map-mode', {});
    if (!r.ok) toast.warn(r.error || 'Could not switch the map view.');
    else paintMapMode(r.mode);
  }
  function paintMapMode(mode) {
    const btn = $('#pc-mapmode', root); if (!btn || !mode) return;
    btn.dataset.mode = mode;
    btn.textContent = mapModeLabel(mode);
    // Auto and 3D both light up, as on the map: in either the stream may be
    // in a player's view, so a glance says "not just the flat map".
    const live = mode === '3d' || mode === 'auto';
    btn.classList.toggle('btn-outline-success', live);
    btn.classList.toggle('btn-outline-secondary', !live);
  }
  async function marker() {
    const inp = $('#pc-marker-note', root);
    const r = await api.post(`${P}/marker`, { note: inp.value });
    inp.value = '';
    if (r.warning) toast.warn(r.warning); else toast.success(`Marker: ${r.marker.note}`);
  }
  async function spotlight(key) {
    const r = await api.post(`${P}/spotlight`, { key });
    if (!r.ok) toast.warn(r.error);
  }
  async function buildCloseups() {
    const btn = $('#pc-build-closeups', root); if (btn) btn.disabled = true;
    try {
      const r = await api.post(`${P}/build-closeups`);
      if (!r.ok) toast.warn(r.error);
      else toast.success(`Closeup scenes ready: ${r.built.length}` + (r.skipped.length ? ` (no tile yet: ${r.skipped.join(', ')})` : ''));
    } finally { if (btn) btn.disabled = false; }
  }
  async function muteAll() {
    // "all" on the mute endpoint leaves the DM out; "all but DM" also means
    // the DM must be HEARD, so a muted DM is unmuted in the same stroke.
    await api.post('/ttrpg/obs/api/mute', { all: true, muted: true });
    await api.post('/ttrpg/obs/api/mute', { character_id: -1, muted: false }, { quiet: true }).catch(() => {});
    toast.info('Players muted, DM live');
    loadRows();
  }
  // "all" on the mute endpoint deliberately leaves the DM out; the DM is a
  // separate call with their tile id (-1).
  async function muteEveryone(muted) {
    await api.post('/ttrpg/obs/api/mute', { all: true, muted });
    await api.post('/ttrpg/obs/api/mute', { character_id: -1, muted }, { quiet: true }).catch(() => {});
    toast.info(muted ? 'Everyone muted, DM included' : 'Everyone unmuted');
    loadRows();
  }
  async function connectObs() {
    const btn = $('#pc-obs-connect', root); if (btn) btn.disabled = true;
    if (btn) { btn.className = 'btn btn-sm text-nowrap btn-warning'; btn.innerHTML = 'OBS &hellip; connecting'; }
    try {
      const r = await api.post(`${P}/obs/connect`, null, { quiet: true });
      toast[r.ok ? 'info' : 'warn'](r.message || (r.ok ? 'Connecting…' : 'Could not connect'));
      // Follow the handshake closely for a few seconds instead of waiting
      // for the next event or the slow safety poll.
      if (r.ok && onRefresh) for (let i = 1; i <= 8; i++) setTimeout(() => { if (!state || !state.connected) onRefresh(); }, i * 1000);
    } catch (e) { toast.error(e.message || 'Could not connect'); }
    finally { setTimeout(() => { if (btn) btn.disabled = false; }, 1500); }
  }
  async function rebuild() {
    const btn = $('#pc-rebuild', root); if (btn) btn.disabled = true;
    try {
      const r = await api.post('/ttrpg/obs/api/build-party', null, { quiet: true });
      if (!r.ok) toast.error(r.error || 'Build failed');
      else {
        const w = r.warnings || [];
        toast[w.length ? 'warn' : 'success'](w.length ? `Rebuilt with ${w.length} warning${w.length === 1 ? '' : 's'}: ${w[0]}` : 'Scenes rebuilt');
      }
    } catch (e) { toast.error(e.message || 'Build failed'); }
    finally { if (btn) btn.disabled = false; }
  }
  async function loadRows() {
    try {
      const d = await api.get('/ttrpg/obs/api/state', { quiet: true });
      // source (the meter key) is resolved in paintStrip() from state.shots,
      // not from this row's r.scene — that's the shared party scene, not the
      // per-character cam OBS actually meters.
      rows = (d.rows || []).filter(r => r.on_stream).map(r => ({
        name: r.name, character_id: r.character_id, muted: !!r.muted,
        volume_db: Number(r.volume_db) || 0,
      }));
      musicDb = Number(d.music_volume_db) || 0;
      paintStrip();
    } catch (e) { /* OBS state is optional here */ }
  }
  async function loadScenes() {
    // The tiles are exactly the DM's session / battle-map list: the active
    // session's campaign scenes, from the state document (state.scenes).
    // /api/v1/home only decorates them (colour, LED pattern, WLED effect,
    // queue state) when it happens to know the scene.
    const home = await api.get('/api/v1/home', { quiet: true }).then(d => d.scenes || []).catch(() => []);
    const deco = new Map(home.map(s => [s.scene_ID, s]));
    scenes = ((state && state.scenes) || []).map(s => ({ ...(deco.get(s.scene_ID) || {}), ...s }));
    paintScenes();
  }

  // ── wiring ──
  function wire() {
    ctx.on(root, 'click', async (e) => {
      const spot = e.target.closest('.pc-spot'); if (spot) { e.stopPropagation(); return spotlight(spot.dataset.spot); }
      const shot = e.target.closest('.pc-shot'); if (shot && !shot.disabled && !shot.classList.contains('unbuilt')) return arm(shot.dataset.shot);
      const sc = e.target.closest('[data-scene]'); if (sc) { await api.post(`/activatescenes/?id=${sc.dataset.scene}`); return; }
      const sp = e.target.closest('[data-sp]'); if (sp) { await api.post(sp.dataset.sp); return; }
      const mu = e.target.closest('[data-mute]'); if (mu) { await api.post('/ttrpg/obs/api/mute', { character_id: Number(mu.dataset.mute), muted: mu.dataset.muted !== '1' }); return loadRows(); }
      switch (e.target.closest('button, .pc-clock') && (e.target.closest('button, .pc-clock').id)) {
        case 'pc-build-closeups': return buildCloseups();
        case 'pc-kill': await api.post('/killqueue'); return api.post('/activatescenes/?id=-1');   // kill, then lights-off teardown
        case 'pc-take': return take();
        case 'pc-mapmode': return mapMode();
        case 'pc-marker': return marker();
        case 'pc-barge': { const r = await api.post(`${P}/barge`, { on: !(state && state.producer && state.producer.on_screen) }); if (r.warnings && r.warnings.length) toast.warn(r.warnings[0]); return; }
        case 'pc-producer-save': { const r = await api.post(`${P}/profile`, { name: $('#pc-producer-name', root).value, icon: $('#pc-producer-icon', root).value }); toast.success(`On stream as ${r.icon ? r.icon + ' ' : ''}${r.name}`); return; }
        case 'pc-markers-clear': if (confirm('Clear every marker of this session?')) return api.del(`${P}/markers`); return;
        case 'pc-mute-all': return muteAll();
        case 'pc-mute-everyone': return muteEveryone(true);
        case 'pc-unmute-all': return muteEveryone(false);
        case 'pc-rebuild': return rebuild();
        case 'pc-obs-connect': return connectObs();
        case 'pc-count-start': return api.post(`${P}/countdown`, { seconds: 60 * (Number($('#pc-count-min', root).value) || 10) });
        case 'pc-count-clear': return api.post(`${P}/countdown`, { clear: true });
        case 'pc-clock': if (confirm('Reset the session clock?')) return api.post(`${P}/clock/reset`); return;
      }
    });
    ctx.on($('#pc-fade-type', root), 'change', setFade);
    ctx.on($('#pc-fade-ms', root), 'change', setFade);
    // A select keeps keyboard focus after a pick, and the hotkey handler
    // below ignores keys aimed at form fields — so Shift+1, Enter and the
    // rest went dead until the operator clicked elsewhere. Hand focus back.
    ctx.on(root, 'change', e => { if (e.target.matches && e.target.matches('select.pc-fade-sel')) e.target.blur(); });
    ctx.on($('#pc-autocam', root), 'change', e => api.post(`${P}/auto-cam-pause`, { paused: !e.target.checked }));
    ctx.on($('#pc-vol', root), 'change', e => api.post('/set_volume', { volume: Number(e.target.value) }));
    // OBS faders: label and throttled post while dragging, a final post on
    // release, double-click back to unity. Delegated: the strip is re-rendered.
    ctx.on(root, 'input', e => { const f = e.target.closest('.pc-fader'); if (f) setFader(f, Number(f.value), false); });
    ctx.on(root, 'change', e => { const f = e.target.closest('.pc-fader'); if (f) setFader(f, Number(f.value), true); });
    ctx.on(root, 'dblclick', e => { const f = e.target.closest('.pc-fader'); if (f) setFader(f, 0, true); });
    ctx.on(root, 'pointerdown', e => { if (e.target.closest('.pc-fader')) faderBusy = true; });
    ctx.on(document, 'pointerup', () => { if (!faderBusy) return; faderBusy = false; if (stripDirty) paintStrip(); });
    ctx.on($('#pc-marker-note', root), 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); marker(); } });
    ctx.on(document, 'keydown', e => {
      const t = e.target; if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // Marker and Escape stay live even while OBS is disconnected: a marker
      // is just a stored row, and Escape's arm-nothing no-op needs no OBS call.
      if (e.key === 'k' || e.key === 'K') { marker(); e.preventDefault(); return; }
      if (e.key === 'v' || e.key === 'V') { mapMode(); e.preventDefault(); return; }
      // Escape arms nothing: the server forgets the armed shot and leaves
      // OBS's preview alone (it is still what the next Take would put up).
      if (e.key === 'Escape') { api.post(`${P}/arm`, { key: '' }, { quiet: true }).catch(() => {}); return; }
      if (!state || !state.connected) return;   // same OBS-backed gate the mouse controls respect
      // Shot hotkeys come from the state document (the Broadcast page's
      // mapping: digits = tiles in party order, 0 party, B map, I intermission, P pre-show, O post-show, F blank screen).
      const hk = e.key.length === 1 ? e.key.toUpperCase() : '';
      // Shift+digit spotlights that player inside the party scene (arranges it; no cut);
      // Shift+0 evens the table out. Digit codes are used because Shift
      // changes e.key on many layouts (Shift+1 -> '!').
      if (e.shiftKey && /^Digit[0-9]$/.test(e.code)) {
        const digit = e.code.slice(5);
        if (digit === '0') spotlight('');
        else { const s = (state.shots || []).find(x => x.hotkey === digit); if (s && s.kind !== 'special') spotlight(s.key); }
        e.preventDefault(); return;
      }
      const target = hk && /^[0-9BIPOF]$/.test(hk) ? (state.shots || []).find(s => s.hotkey === hk) : null;
      if (target) { const b = root.querySelector(`.pc-shot[data-shot="${target.key}"]`); if (b && !b.disabled && !b.classList.contains('unbuilt')) arm(target.key); e.preventDefault(); }
      else if (e.key === 'Enter') { take(); e.preventDefault(); }
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

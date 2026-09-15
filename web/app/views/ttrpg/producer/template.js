// Producer console markup. Everything dynamic is painted by console.js; this
// renders the frame once from the first state document.
import { html } from '../../../lib/dom.js';

const shotTile = (s, i) => html`<button type="button" class="pc-shot ${s.built ? '' : 'unbuilt'}" data-shot="${s.key}"
  title="${s.built ? 'Arm ' + s.label : s.label + (s.kind === 'special' ? ': scene not built — run Build on the Broadcast page' : ': closeup scene not built — click Build closeups')}">
  <img alt="" data-snap="${s.key}"><span class="pc-key">${s.hotkey || ''}</span>
  ${s.kind === 'special' ? '' : html`<span class="pc-spot" data-spot="${s.key}" title="Spotlight ${s.label} in the party scene — sets the layout, never cuts (Shift+${s.hotkey || 'click'})">&#9728;</span>`}
  <span class="pc-shot-label">${s.label}</span></button>`;

export function render(d) {
  return html`<div class="pc" id="pc">
  <div class="pc-banner mb-1" id="pc-banner" hidden><span id="pc-banner-text">OBS is not connected — shots, Take and the OBS audio strip are disabled.</span></div>
  <div class="pc-pvw"><div class="pc-mon pvw"><img alt="" id="pc-pvw-img"><span class="pc-tag">Preview</span>
    <span class="pc-by" id="pc-pvw-name">${d.preview || 'nothing armed'}</span></div></div>
  <div class="pc-pgm"><div class="pc-mon pgm"><img alt="" id="pc-pgm-img"><span class="pc-tag">Program &#9679; LIVE</span>
    <span class="pc-by" id="pc-pgm-name">${d.program}</span></div></div>

  <div class="pc-side ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1">
      <span class="d-flex align-items-center gap-1">
        <button type="button" class="btn btn-sm text-nowrap ${d.connected ? 'btn-success' : 'btn-danger'}" id="pc-obs-connect"
          title="${d.connected ? 'Connected to OBS — click to reconnect' : 'Not connected — click to connect'}">OBS ${d.connected ? '&#10003; connected' : '&#10007; connect'}</button>
        <span class="badge ${d.streaming ? 'bg-danger' : 'bg-secondary'}" id="pc-stream-pill">STREAM</span>
        <span class="badge ${d.recording ? 'bg-danger' : 'bg-secondary'}" id="pc-rec-pill">REC</span></span></div>
    <div class="small text-secondary"><span id="pc-updated" title="When this console last received the server's state">updated —</span> &middot; <span id="pc-consoles">${d.consoles} console${d.consoles === 1 ? '' : 's'}</span></div>
    <button type="button" class="btn btn-sm btn-outline-secondary w-100 mt-1" id="pc-rebuild" title="Run the Broadcast page's Build: party scene, map, show cards, audio and the closeup scenes">&#128295; Rebuild scenes</button>
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
    <div class="mb-2" id="pc-closeups-note" hidden><button type="button" class="btn btn-sm btn-outline-warning" id="pc-build-closeups"
      title="Create one full-frame scene per player and the DM from the tiles already in the party scene (no new feeds)">&#127909; Build closeups</button>
      <span class="small text-secondary ms-2">Player shots need their closeup scenes in OBS.</span></div>
    <div class="d-flex flex-wrap align-items-center gap-2">
      <button type="button" class="btn btn-danger pc-take" id="pc-take" title="Cut the armed Preview shot to Program (Enter)">TAKE &#9654;</button>
      <button type="button" class="btn btn-outline-danger pc-take" id="pc-auto" title="Auto transition: fade the armed Preview shot to Program (Space). Arm a shot first — click a tile or press its key.">AUTO &#10227; <span class="small fw-normal">fade</span></button>
      <button type="button" class="btn btn-outline-warning btn-sm" id="pc-group" title="Even the party out again — sets the layout, never cuts (Shift+0)">&#9728; Group</button>
      <select class="form-select form-select-sm" id="pc-transition" style="width:auto">
        ${d.transitions.map(t => html`<option value="${t}" ${t === d.transition ? 'selected' : ''}>${t}</option>`)}</select>
      <input type="number" class="form-control form-control-sm" id="pc-ms" value="${d.transition_ms || 300}" min="0" max="5000" step="50" style="width:5.5rem" title="ms">
      <span class="small text-secondary ms-auto">1–9 arm player &middot; Shift+1–9 spotlight in party (no cut) &middot; Shift+0 group &middot; 0 party &middot; B map &middot; I intermission &middot; Enter take &middot; Space auto &middot; M mute all &middot; K marker &middot; Esc clear</span>
    </div>
  </div>

  <div class="pc-sp ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1 gap-2"><b>ScenePlay</b>
      <span class="small text-truncate" id="pc-active-scene">no scene active</span>
      <span class="small text-secondary text-truncate ms-auto" id="pc-nowplaying"></span></div>
    <div class="d-flex flex-wrap gap-1 mb-2" id="pc-scenes"></div>
    <div class="d-flex gap-1">
      <button type="button" class="btn btn-sm btn-outline-secondary" data-sp="/nextsong">Skip &#9197;</button>
      <button type="button" class="btn btn-sm btn-outline-danger" data-sp="/killqueue">Kill &#9209;</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-sp="/api/lights-off">Lights off</button>
      <input type="range" class="form-range ms-2" id="pc-vol" min="0" max="100" style="width:8rem" title="music volume"></div>
  </div>

  <div class="pc-audio ttrpg-card p-2">
    <div class="d-flex justify-content-between align-items-center mb-1"><b>Audio</b>
      <span class="d-flex gap-1">
        <button type="button" class="btn btn-sm btn-danger" id="pc-mute-all" title="Mute every player and make sure the DM is live — unmutes the DM if needed (M)">MUTE ALL BUT DM</button>
        <button type="button" class="btn btn-sm btn-outline-danger" id="pc-mute-everyone" title="Mute every player and the DM">Mute all</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="pc-unmute-all" title="Unmute every player and the DM">Unmute all</button></span></div>
    <div class="pc-strip" id="pc-strip"></div>
  </div>
</div>`;
}

// base_ttrpg.html: role-aware navbar, relay health banner, sync toast host.
import { html, render, raw } from '../lib/dom.js';
import { store } from '../store.js';
import { sse } from '../sse.js';
import { api } from '../api.js';
import { pillsHtml } from '../ui/nav_pills.js';
import { initThemePicker } from '../theme.js';

let _offs = [];

function navHtml() {
  const u = store.get('user');
  const isDm = !!(u && u.role === 'dm');
  const v = (store.get('serverInfo') || {}).version || '';
  return html`<nav class="navbar navbar-expand-lg ttrpg-nav"><div class="container-fluid">
    ${isDm ? html`<a class="navbar-brand" href="/">&#9654; ScenePlay</a>` : raw('')}
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#ttrpgNav"><span class="navbar-toggler-icon"></span></button>
    <div class="collapse navbar-collapse" id="ttrpgNav">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
      ${!u ? raw('') : isDm ? html`
        <li class="nav-item"><a class="nav-link" href="/ttrpg">Dashboard</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/sessions">Sessions</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/battlemap/maps">Maps</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/battlemap/active" title="Jump to the live battle map">&#127919; Current Map</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/characters">Characters</a></li>
        <li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" id="attributesDropdown" role="button" data-bs-toggle="dropdown" aria-expanded="false">Attributes</a>
          <ul class="dropdown-menu" aria-labelledby="attributesDropdown">
            <li><a class="dropdown-item" href="/ttrpg/reference/armor">Armor</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/classes">Classes</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/equipment">Equipment</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/feats">Feats</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/races">Races</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/skills">Skills</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/spells">Spells</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/subclasses">Subclasses</a></li>
            <li><a class="dropdown-item" href="/ttrpg/reference/weapons">Weapons</a></li>
          </ul></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/monsters">Monsters &amp; Assets</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/relay">&#127760; Relay</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/obs" title="OBS scene control">&#127909; Broadcast</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/register">Manage Users</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/reference/settings" title="D&amp;D API settings">&#9881; DND API</a></li>` : html`
        <li class="nav-item"><a class="nav-link" href="/ttrpg/my-character">My Character</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/battlemap/active">&#9776; Battle Map</a></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/reference/library">&#128218; Library</a></li>`}
      </ul>
      <ul class="navbar-nav ms-auto align-items-center">
      ${u ? html`<li class="nav-item"><span class="nav-link" style="color:var(--ttrpg-accent);">${u.display_name} ${isDm ? raw('<span class="badge" style="background:var(--ttrpg-accent);color:var(--sp-on-accent);">DM</span>') : raw('')}</span></li>
        <li class="nav-item"><a class="nav-link" href="/ttrpg/change-password">Change Password</a></li>
        <li class="nav-item"><a class="nav-link" href="/logout">Logout</a></li>` : raw('')}
      </ul>
    </div>
    <span id="sp-pills">${pillsHtml(store.get('health'), { dmOnly: true, isDm })}</span>
    <span class="sp-version" title="ScenePlay version">v${v}<span class="sp-conn-dot" id="sp-conn" data-state="${store.get('sseState')}" title="Live updates"></span></span>
    <div class="sp-theme-wrap"><button id="sp-theme-btn" type="button" class="btn nav-link" title="Color theme">&#9670;</button>
      <div id="sp-theme-panel"><div class="sp-panel-title">Color Theme</div><div id="sp-swatches"></div></div></div>
  </div></nav>
  ${isDm ? html`<div id="relay-health-banner" class="sp-banner-danger" style="display:none;"><span style="font-weight:700;">&#9888; Relay problem:</span> <span id="relay-health-msg"></span> <a href="/ttrpg/relay">Open Relay admin &rarr;</a></div>` : raw('')}`;
}

function _applyRelay(d) {
  const banner = document.getElementById('relay-health-banner'), msg = document.getElementById('relay-health-msg');
  if (!banner) return;
  if (d && d.enabled && !d.ok && d.problems && d.problems.length) { msg.textContent = d.problems.join(' — '); banner.style.display = ''; }
  else banner.style.display = 'none';
}

export async function mount(shell) {
  render(shell, html`<div id="sp-nav"></div><main id="sp-outlet" class="container-fluid mt-3"></main>
    <div id="sync-toast" class="ttrpg-card p-3" style="display:none;position:fixed;bottom:22px;right:22px;width:290px;z-index:9000;box-shadow:0 4px 24px rgba(0,0,0,.6);">
      <div class="d-flex justify-content-between align-items-center mb-1"><span id="sync-toast-title" class="fw-bold small" style="color:var(--ttrpg-accent);">Syncing…</span><span id="sync-toast-pct" class="small" style="color:var(--ttrpg-accent);">0%</span></div>
      <div class="progress mb-2" style="height:7px;background:var(--sp-surface);border-radius:4px;"><div id="sync-toast-bar" class="progress-bar" role="progressbar" style="width:5%;background:var(--ttrpg-accent);transition:width .35s ease;border-radius:4px;"></div></div>
      <div id="sync-toast-label" class="small text-muted">Fetching list from API…</div></div>`);
  const nav = shell.querySelector('#sp-nav');
  const redraw = () => { render(nav, navHtml()); initThemePicker(); };
  redraw();
  _offs.push(store.subscribe('health', h => { const p = shell.querySelector('#sp-pills'); if (p) render(p, pillsHtml(h, { dmOnly: true, isDm: store.isDm() })); }));
  _offs.push(store.subscribe('user', redraw));
  _offs.push(store.subscribe('serverInfo', redraw));
  _offs.push(store.subscribe('sseState', s => { const d = shell.querySelector('#sp-conn'); if (d) d.dataset.state = s; }));
  if (store.isDm()) {
    _offs.push(sse.subscribe('relay', _applyRelay, { fallback: { every: 15000, fetch: () => api.get('/ttrpg/relay/api/health', { quiet: true }) } }));
  }
  return shell.querySelector('#sp-outlet');
}

export function unmount() { for (const o of _offs.splice(0)) o(); }

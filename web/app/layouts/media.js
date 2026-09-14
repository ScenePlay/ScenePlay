// base.html: navbar + player bar; persists across media routes.
import { html, render, raw } from '../lib/dom.js';
import { store } from '../store.js';
import { pillsHtml } from '../ui/nav_pills.js';
import { initThemePicker } from '../theme.js';
import { mountPlayerBar, unmountPlayerBar } from '../ui/player_bar.js';

let _offs = [];

function navHtml() {
  const locked = store.get('sceneplayLocked') && !store.isDm();
  const v = (store.get('serverInfo') || {}).version || '';
  return html`<nav class="navbar navbar-expand-lg sp-nav"><div class="container-fluid">
    <a class="navbar-brand" href="${locked ? '/ttrpg' : '/'}">ScenePlay</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarSupportedContent" aria-controls="navbarSupportedContent" aria-expanded="false"><span class="navbar-toggler-icon"></span></button>
    <div class="collapse navbar-collapse" id="navbarSupportedContent"><ul class="navbar-nav me-auto mb-2 mb-lg-0">
      ${locked ? raw('') : html`<li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown" aria-expanded="false">Tables</a>
        <ul class="dropdown-menu">
          <li><a class="dropdown-item" href="/campaigns">Campaigns</a></li>
          <li><a class="dropdown-item" href="/scenes">Scenes</a></li>
          <li><a class="dropdown-item" href="/scenePattern">Scene RPiLED</a></li>
          <li><a class="dropdown-item" href="/wledPallette">Scene WLED</a></li>
          <li><a class="dropdown-item" href="/musicScene">Scene Music</a></li>
          <li><a class="dropdown-item" href="/videoScene">Scene Video</a></li>
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item" href="/music">Music Media</a></li>
          <li><a class="dropdown-item" href="/videomedia">Video Media</a></li>
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item" href="/ledconfig">LED Config</a></li>
          <li><a class="dropdown-item" href="/serverIP">Servers</a></li>
          <li><a class="dropdown-item" href="/cronSchedule">Cron Schedules</a></li>
        </ul></li>
        <li class="nav-item"><a class="nav-link" href="/utilities">Utilities</a></li>`}
      <li class="nav-item"><a class="nav-link" href="/ttrpg">&#9876; TTRPG</a></li>
    </ul></div>
    <span id="sp-pills">${pillsHtml(store.get('health'))}</span>
    <span class="sp-version" title="ScenePlay version">v${v}<span class="sp-conn-dot" id="sp-conn" data-state="${store.get('sseState')}" title="Live updates"></span></span>
    <div class="sp-theme-wrap"><button id="sp-theme-btn" type="button" class="btn nav-link" title="Color theme">&#9670;</button>
      <div id="sp-theme-panel"><div class="sp-panel-title">Color Theme</div><div id="sp-swatches"></div></div></div>
  </div></nav>`;
}

export async function mount(shell) {
  render(shell, html`<div id="sp-nav"></div><div id="container"><div id="content" class="sp-player-bar"></div></div><main id="sp-outlet"></main>`);
  const nav = shell.querySelector('#sp-nav');
  const redraw = () => { render(nav, navHtml()); initThemePicker(); };
  redraw();
  _offs.push(store.subscribe('health', h => { const p = shell.querySelector('#sp-pills'); if (p) render(p, pillsHtml(h)); }));
  _offs.push(store.subscribe('sceneplayLocked', redraw));
  _offs.push(store.subscribe('user', redraw));
  _offs.push(store.subscribe('serverInfo', redraw));
  _offs.push(store.subscribe('sseState', s => { const d = shell.querySelector('#sp-conn'); if (d) d.dataset.state = s; }));
  await mountPlayerBar(shell.querySelector('#content'));
  return shell.querySelector('#sp-outlet');
}

export function unmount() {
  for (const o of _offs.splice(0)) o();
  unmountPlayerBar();
}

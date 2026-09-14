// Battle map view markup (templates/ttrpg/battlemap.html) rendered from
// GET /api/v1/battlemap/:id/page. The verbatim map.js drives it.
import { html, raw } from '../../../lib/dom.js';

const strip = (id, onclick, title, inner, h = 44, fs = '1.5rem', extra = '') => html`<button ${id ? raw(`id="${id}"`) : ''} onclick="${onclick}" title="${title}" ${raw(extra)} style="width:44px;height:${h}px;border-radius:${h === 44 ? 8 : 6}px;border:1px solid #555;background:var(--ttrpg-primary);color:var(--ttrpg-accent);font-size:${fs};font-weight:${h === 44 ? 900 : 700};line-height:1;cursor:pointer;">${raw(inner)}</button>`;
const rule = () => raw('<div style="width:28px;border-top:1px solid #444;margin:2px 0;"></div>');
const hpColor = p => p > 50 ? '#28a745' : p > 20 ? '#ffc107' : '#dc3545';
const sbHp = (kind, id, cur, max, pct, onMap) => html`<div class="sb-hp-row" ${onMap ? '' : 'style="display:none;"'}><div class="d-flex align-items-center gap-1 mt-1">
  <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="adjustSidebarHp('${kind}', ${id}, -sbAmt(this))">&#9660;</button>
  <input type="number" class="sb-amt form-control form-control-sm text-center" value="1" min="1" style="width:34px;padding:1px 0;font-size:.7rem;">
  <button class="btn btn-sm btn-outline-success py-0 px-1" onclick="adjustSidebarHp('${kind}', ${id}, +sbAmt(this))">&#9650;</button>
  <span class="sb-hp" style="color:var(--ttrpg-accent);font-size:.72rem;margin-left:2px;">${cur}/${max}</span></div>
  <div style="height:3px;background:var(--sp-border);border-radius:2px;margin-top:3px;"><div class="sb-bar" style="height:100%;border-radius:2px;transition:width .3s;width:${pct}%;background:${hpColor(pct)};"></div></div></div>`;
const fxLabelInput = (id, label, extra) => html`<div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label" style="min-width:36px;">${label}</label>${raw(extra)}</div>`;

export const STYLE = `
  body.view-battlemap{overflow:hidden;}
  #map-viewport{flex:1;overflow:auto;background:#0d1117;position:relative;cursor:grab;touch-action:none;overscroll-behavior:none;}
  #map-grid{position:relative;flex-shrink:0;transform:translateZ(0);}
  #map-bg{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;z-index:0;opacity:0.75;pointer-events:none;}
  #map-lines{position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;background-image:linear-gradient(to right, color-mix(in srgb, var(--sp-accent) 25%, transparent) 1px, transparent 1px),linear-gradient(to bottom, color-mix(in srgb, var(--sp-accent) 25%, transparent) 1px, transparent 1px);}
  .map-token{position:absolute;z-index:10;cursor:grab;text-align:center;transition:transform .15s ease;user-select:none;touch-action:none;will-change:transform;contain:layout style;}
  .tok-player:hover .token-portrait{box-shadow:0 0 0 3px rgba(74,158,255,.55),0 0 10px rgba(74,158,255,.35);transition:box-shadow .15s;}
  .tok-monster:hover .token-portrait{box-shadow:0 0 0 3px rgba(204,51,51,.55),0 0 10px rgba(204,51,51,.35);transition:box-shadow .15s;}
  .token-portrait{border-radius:50%;border:2px solid;overflow:hidden;margin:2px auto 0;display:flex;align-items:center;justify-content:center;font-weight:bold;color:#fff;font-size:.9rem;}
  .token-portrait img{width:100%;height:100%;object-fit:cover;}
  .token-hp-bar{height:4px;background:#222;margin:2px 3px;border-radius:2px;} .token-hp-fill{height:100%;border-radius:2px;transition:width .3s;}
  .token-name{font-size:9px;color:#fff;text-shadow:0 0 3px #000,0 0 3px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 2px;line-height:1.3;}
  .token-mine .token-portrait{border-color:#2ecc71 !important;box-shadow:0 0 0 2px #2ecc71,0 0 10px 2px rgba(46,204,113,.55);animation:token-pulse 2.2s ease-in-out infinite;}
  @keyframes token-pulse{0%,100%{box-shadow:0 0 0 2px #2ecc71,0 0 8px 2px rgba(46,204,113,.45);}50%{box-shadow:0 0 0 2px #2ecc71,0 0 18px 4px rgba(46,204,113,.85);}}
  .token-you-arrow{position:absolute;top:-17px;left:50%;transform:translateX(-50%);background:#2ecc71;color:#0d1117;font-size:.55rem;font-weight:800;letter-spacing:.05em;padding:1px 5px;border-radius:3px;white-space:nowrap;pointer-events:none;z-index:20;}
  .token-you-arrow::after{content:'';position:absolute;top:100%;left:50%;transform:translateX(-50%);border:4px solid transparent;border-top-color:#2ecc71;}
  #tok-tooltip{position:fixed;z-index:500;display:none;background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);border-radius:8px;padding:12px 14px;min-width:250px;max-width:360px;pointer-events:none;font-size:.9rem;color:var(--ttrpg-text);box-shadow:0 4px 20px rgba(0,0,0,.7);}
  #tt-layout{display:flex;gap:10px;align-items:flex-start;} #tt-portrait{width:132px;height:132px;object-fit:cover;border-radius:6px;border:2px solid var(--ttrpg-accent);flex-shrink:0;display:none;} #tt-body{flex:1;min-width:0;}
  #tt-hp-bar-wrap{height:7px;background:rgba(0,0,0,0.25);border-radius:3px;margin-bottom:7px;} #tt-hp-bar{height:100%;border-radius:3px;transition:width .3s;}
  .token-dead{opacity:.35;filter:grayscale(1);}
  #fx-panel,#fp-panel{display:none;position:fixed;top:64px;right:16px;z-index:400;width:248px;background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);border-radius:8px;padding:10px 12px;font-size:.82rem;color:var(--ttrpg-text);box-shadow:0 4px 24px rgba(0,0,0,.7);}
  #fp-panel{max-height:calc(100vh - 96px);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;}
  #fp-panel .fx-panel-header{position:sticky;top:-10px;margin:-10px -12px 10px;padding:10px 12px 8px;background:var(--ttrpg-primary);border-radius:8px 8px 0 0;z-index:1;}
  .fx-panel-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-weight:bold;color:var(--ttrpg-accent);cursor:grab;user-select:none;} .fx-panel-header:active{cursor:grabbing;}
  select.fp-tex-select.fp-tex-hidden{display:none;}
  .fp-tex-btn{display:flex;align-items:center;gap:6px;flex:1;min-width:0;text-align:left;cursor:pointer;width:auto;}
  .fp-tex-thumb{flex:0 0 auto;width:22px;height:22px;border-radius:4px;background-size:cover;background-position:center;border:1px solid rgba(0,0,0,.35);}
  .fp-tex-thumb.fp-tex-none{background:repeating-linear-gradient(45deg,#888 0 3px,#bbb 3px 6px);opacity:.55;}
  .fp-tex-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .fp-tex-menu{position:fixed;z-index:500;width:236px;max-height:260px;overflow-y:auto;background:var(--ttrpg-primary);color:var(--ttrpg-text);border:1px solid var(--ttrpg-accent);border-radius:6px;padding:4px;box-shadow:0 6px 24px rgba(0,0,0,.6);font-size:.8rem;}
  .fp-tex-cat{padding:6px 6px 2px;font-size:.68rem;letter-spacing:.05em;text-transform:uppercase;opacity:.65;}
  .fp-tex-row{display:flex;align-items:center;gap:8px;width:100%;padding:3px 6px;background:none;border:0;border-radius:4px;color:inherit;text-align:left;cursor:pointer;}
  .fp-tex-row:hover,.fp-tex-row.active{background:color-mix(in srgb,var(--ttrpg-accent) 25%,transparent);} .fp-tex-row .fp-tex-thumb{width:30px;height:30px;}
  .fx-close-btn{background:none;border:none;color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);cursor:pointer;font-size:.95rem;padding:0;line-height:1;min-width:32px;min-height:32px;display:inline-flex;align-items:center;justify-content:center;}
  .fx-close-btn:hover,.fx-close-btn:active{color:var(--ttrpg-accent);}
  .fx-shape-btn{flex:1;padding:8px 0;background:var(--ttrpg-surface);border:1px solid var(--sp-border);border-radius:5px;color:var(--ttrpg-text);cursor:pointer;font-size:1rem;transition:background .15s,border-color .15s;}
  .fx-shape-btn:hover{border-color:var(--ttrpg-accent);color:var(--ttrpg-accent);} .fx-shape-btn.active{background:rgba(201,168,76,.18);border-color:var(--ttrpg-accent);color:var(--ttrpg-accent);}
  .fx-label{font-size:.75rem;color:color-mix(in srgb,var(--ttrpg-text) 72%,transparent);}
  .fx-color-input{width:36px;height:24px;padding:1px;border:1px solid var(--sp-border);border-radius:3px;background:none;cursor:pointer;}
  #dice-map-panel{display:none;position:fixed;top:80px;right:16px;z-index:400;width:268px;max-height:calc(100dvh - 100px);overflow-y:auto;background:color-mix(in srgb,var(--ttrpg-primary) 75%,white);border:1px solid var(--ttrpg-accent);border-radius:8px;padding:10px 12px;font-size:.82rem;color:var(--ttrpg-text);box-shadow:0 4px 24px rgba(0,0,0,.7);user-select:none;}
  #dice-drag-handle{cursor:grab;} #dice-drag-handle:active{cursor:grabbing;}
  #dice-map-panel.minimized > *:not(#dice-drag-handle){display:none !important;}
  .dice-quickref{border-top:1px solid var(--sp-border);padding-top:8px;margin-bottom:8px;}
  .qref-title{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--sp-muted);font-weight:600;margin-bottom:6px;} .qref-hint{text-transform:none;letter-spacing:0;font-weight:400;font-size:.68rem;}
  .qref-row{display:flex;gap:6px;align-items:flex-start;margin-bottom:5px;} .qref-label{flex-shrink:0;width:56px;font-size:.62rem;text-transform:uppercase;color:var(--sp-muted);padding-top:3px;letter-spacing:.04em;}
  .qref-chips{display:flex;flex-wrap:wrap;gap:4px;flex:1;min-width:0;}
  .qref-chip{display:inline-flex;align-items:center;gap:3px;font-size:.72rem;padding:2px 7px;background:var(--ttrpg-surface);border:1px solid var(--sp-border);border-radius:10px;color:var(--ttrpg-text);}
  .qref-sub{color:var(--sp-muted);font-size:.66rem;} .qref-click{cursor:pointer;} .qref-click:hover{border-color:var(--ttrpg-accent);color:var(--ttrpg-accent);} .qref-click:hover .qref-sub{color:var(--ttrpg-accent);}
  #dice-map-panel.minimized{overflow-y:hidden;}
  .obs-offline{opacity:.82 !important;filter:grayscale(.7);border-style:dashed !important;}
  .obs-two-line{height:34px !important;line-height:1.1 !important;white-space:normal;padding:0 2px;}
  #notes-map-panel{display:none;position:fixed;top:96px;right:32px;z-index:401;width:450px;max-width:calc(100vw - 48px);max-height:calc(100dvh - 120px);overflow-y:auto;background:color-mix(in srgb,var(--ttrpg-primary) 75%,white);border:1px solid var(--ttrpg-accent);border-radius:8px;padding:10px 12px;font-size:.82rem;color:var(--ttrpg-text);box-shadow:0 4px 24px rgba(0,0,0,.7);}
  #notes-drag-handle{cursor:grab;} #notes-drag-handle:active{cursor:grabbing;}
  #notes-map-panel.minimized > *:not(#notes-drag-handle){display:none !important;} #notes-map-panel.minimized{overflow-y:hidden;} #notes-map-panel.minimized #notes-drag-handle{margin-bottom:0;}
  .map-note-row{background:var(--ttrpg-surface);border:1px solid var(--sp-border);border-radius:6px;padding:6px 9px;cursor:pointer;} .map-note-row:hover{border-color:var(--ttrpg-accent);}
  .map-note-row .mn-title{font-weight:600;color:var(--ttrpg-accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;} .map-note-row .mn-snip{color:var(--sp-muted);font-size:.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;} .map-note-row .mn-when{color:var(--sp-muted);font-size:.64rem;}
  .map-dice-btn{min-width:36px;padding:6px 4px;font-size:.78rem;} .stat-mod-btn{min-width:40px;line-height:1.1;padding:2px 4px;font-size:.72rem;} .sidebar-btn{min-height:36px;min-width:36px;}
  .map-dice-btn.active{background:var(--ttrpg-accent) !important;border-color:var(--ttrpg-accent) !important;color:var(--sp-on-accent) !important;}
  .map-die-val{display:inline-block;padding:1px 5px;border-radius:4px;background:color-mix(in srgb,var(--sp-accent) 18%,transparent);border:1px solid var(--sp-border);margin:1px;font-weight:600;font-size:.85rem;}
  .map-die-val.nat20{background:#856404;border-color:#ffc107;color:#fff200;} .map-die-val.nat1{background:#6b1a1a;border-color:#dc3545;color:#ffaaaa;} .map-die-val.kept{background:#0d2e0d;border-color:#28a745;color:#7deb7d;font-weight:bold;}
  .map-feed-entry{font-size:.75rem;padding:4px 0;border-bottom:1px solid var(--sp-border);} .map-feed-entry .tot{color:var(--ttrpg-accent);font-weight:bold;}
  #sidebar-wrap{position:relative;flex-shrink:0;}
  @media (max-width:767px){#sidebar{position:absolute;top:0;left:0;height:100%;z-index:500;width:min(260px,78vw);box-shadow:var(--sp-shadow-2);} #sidebar.sb-collapsed{box-shadow:none;}}
  #sidebar{width:200px;height:100%;overflow-y:auto;background:var(--ttrpg-surface);border-right:1px solid var(--ttrpg-accent);padding:8px;transition:width .22s ease,padding .22s ease;box-sizing:border-box;}
  #sidebar.sb-collapsed{width:0;padding:0;overflow:hidden;}
  #sb-toggle:hover{background:var(--sp-hover-bg) !important;color:var(--sp-hover-text) !important;border-color:var(--sp-hover-bg) !important;}
  .sidebar-section-title{font-size:.95rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--sp-heading);padding:4px 0 2px;border-bottom:1px solid var(--sp-border);margin-bottom:4px;}
  .sidebar-entity{padding:4px 0;font-size:.78rem;border-bottom:1px solid var(--sp-border);}
  .sidebar-entity-row{display:flex;align-items:center;justify-content:space-between;gap:4px;}
  .sidebar-entity span{color:var(--ttrpg-text);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:110px;}
  .sidebar-entity-row > span:first-child{flex:1 1 auto;min-width:0;max-width:none;} .sidebar-entity-row > button{flex:0 0 auto;} .obs-live-btn{min-width:36px;text-align:center;}
  .presence-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;background:#444;border:1px solid #555;transition:background .4s,box-shadow .4s;vertical-align:middle;margin-right:3px;}
  .presence-dot.online{background:#28a745;border-color:#28a745;box-shadow:0 0 5px rgba(40,167,69,.7);}
  .move-radius{position:absolute;border:2px dashed #4a9eff;border-radius:50%;background:rgba(74,158,255,.10);box-sizing:border-box;pointer-events:none;z-index:50;}
  .move-radius-label{position:absolute;transform:translate(-50%,-50%);background:rgba(20,30,50,.82);color:#fff;font-size:.8rem;font-weight:700;padding:1px 7px;border-radius:4px;pointer-events:none;z-index:51;white-space:nowrap;}
  .sp-collapse-banner{flex-shrink:0;text-align:center;font:800 15px/1.3 system-ui,sans-serif;letter-spacing:.06em;padding:5px 12px;border-bottom:1px solid var(--ttrpg-accent);background:color-mix(in srgb,var(--ttrpg-accent) 18%,var(--ttrpg-primary));color:var(--ttrpg-text);}
  .sp-collapse-banner.note{font-weight:600;letter-spacing:.02em;} .sp-collapse-banner.warn{background:#7a2e00;color:#ffe2b8;animation:sp-collapse-pulse 1s ease-in-out infinite;} .sp-collapse-banner.down{background:#6b1a1a;color:#ffd0d0;animation:sp-collapse-pulse .6s ease-in-out infinite;}
  @keyframes sp-collapse-pulse{50%{filter:brightness(1.35);}}
  .sp-collapse-panel{flex-shrink:0;display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:6px 12px;border-bottom:1px solid var(--sp-border);background:var(--sp-surface-2);}
`;

function topBar(d) {
  const bm = d.bm, dm = d.is_dm;
  return html`<div class="d-flex justify-content-between align-items-center px-3 py-2 flex-wrap gap-2" style="background:var(--ttrpg-primary);border-bottom:1px solid var(--ttrpg-accent);flex-shrink:0;">
    <div><strong style="color:var(--ttrpg-accent);">${bm.name}</strong><span class="small text-muted ms-2">${bm.grid_cols}&times;${bm.grid_rows}</span></div>
    <div class="d-flex gap-2">
      ${dm ? html`${bm.is_active ? html`<span id="set-active-btn" class="btn btn-sm btn-success disabled" title="This map is live for players">&#9679; Active</span>` : html`<button id="set-active-btn" class="btn btn-sm btn-outline-warning" onclick="setMapActive()" title="Make this the live map players see">Set Active</button>`}
        <a href="/ttrpg/battlemap/session/${d.sess.session_id}" class="btn btn-sm btn-outline-secondary" title="All maps in this session — view, activate, edit">Maps</a>` : ''}
      <button id="dice-map-toggle-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleMapDicePanel()" title="Dice Roller"><span class="dice-ico">&#127922;</span> Dice</button>
      ${dm ? html`<button id="fx-toggle-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleFxPanel()" title="Map effects">&#10022; FX</button>
        <button id="fp-toggle-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleFpPanel()" title="Floorplan editor — draw the walls/doors/elevation that 3D mode extrudes">&#9635; Walls</button>
        <button id="notes-toggle-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleMapNotesPanel()" title="DM notes for this map (players never see these)">&#128221; Notes</button>
        ${d.sess ? html`<button id="collapse-toggle-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleCollapsePanel()" title="Dungeon Crawler Carl: level-collapse countdown and note (shown to players, the portal and the stream)" style="${d.collapse ? '' : 'display:none;'}">&#9201; Collapse</button>` : ''}` : ''}
      <a href="/ttrpg/my-character" class="btn btn-sm btn-outline-secondary">Character(s)</a>
      ${dm ? html`<button id="dice-clear-btn" class="btn btn-sm btn-outline-secondary" onclick="clearRollFeed(this)" title="Empty the roll feed for everyone — this map, every player's map and the stream overlay">&#128465; Clear Rolls</button>` : ''}
      <button id="fullscreen-btn" class="btn btn-sm btn-outline-secondary" onclick="toggleFullscreen()" title="Full screen">&#9974; Full screen</button>
      <div id="sfx-ctrl" style="display:inline-flex;align-items:center;gap:6px;background:var(--sp-surface-2);border:1px solid var(--sp-border);border-radius:16px;padding:2px 8px;font:600 12px system-ui,sans-serif;user-select:none;">
        <button id="sfx-toggle" type="button" title="Sound is on by default — click to mute / unmute" style="background:none;border:none;cursor:pointer;font:inherit;line-height:1;padding:0;white-space:nowrap;color:var(--sp-heading);">&#128266; Sound: ON</button>
        <input type="range" id="sfx-vol" min="0" max="100" value="80" title="SFX volume" style="width:64px;accent-color:var(--sp-accent);cursor:pointer;">
        <button id="sfx-choose" type="button" title="Choose which sound plays for each action" onclick="if(window.SFX)SFX.openChooser()" style="background:none;border:1px solid var(--sp-accent);border-radius:12px;cursor:pointer;font:inherit;line-height:1;padding:2px 8px;white-space:nowrap;color:var(--sp-heading);">&#9881; Sounds</button></div></div></div>`;
}

function collapsePanel(d) {
  if (!(d.is_dm && d.sess)) return '';
  return html`<div id="collapse-panel" class="sp-collapse-panel" style="display:none;">
    <span class="fw-bold" style="color:var(--ttrpg-accent);">&#9201; Level collapse</span><label class="small mb-0">Countdown</label>
    <input type="number" id="collapse-days" class="form-control form-control-sm" value="0" min="0" max="365" style="width:58px;" title="Days until the level collapses"><span class="small">d</span>
    <input type="number" id="collapse-hours" class="form-control form-control-sm" value="1" min="0" max="23" style="width:58px;" title="Hours"><span class="small">h</span>
    <input type="number" id="collapse-mins" class="form-control form-control-sm" value="0" min="0" max="59" style="width:58px;" title="Minutes"><span class="small">m</span>
    <button class="btn btn-sm btn-ttrpg" onclick="collapseStart()" title="Start (or restart) the countdown from now">&#9654; Start</button>
    <button class="btn btn-sm btn-outline-secondary" onclick="collapseAdjust(-5)" title="Take 5 minutes off">&#8722;5m</button><button class="btn btn-sm btn-outline-secondary" onclick="collapseAdjust(5)" title="Add 5 minutes">+5m</button>
    <button class="btn btn-sm btn-outline-secondary" onclick="collapseAdjust(-60)" title="Take an hour off">&#8722;1h</button><button class="btn btn-sm btn-outline-secondary" onclick="collapseAdjust(60)" title="Add an hour">+1h</button><button class="btn btn-sm btn-outline-secondary" onclick="collapseAdjust(1440)" title="Add a day">+1d</button>
    <button class="btn btn-sm btn-outline-danger" onclick="collapseClear()" title="Stop the countdown (keeps the note)">&#9632; Stop</button>
    <label class="small mb-0 ms-2">Note</label><input type="text" id="collapse-note" class="form-control form-control-sm" maxlength="200" placeholder="Stairs: NE tower &amp; S hall&#8230;" style="flex:1;min-width:160px;" onkeydown="if(event.key==='Enter')collapseSaveNote()">
    <button class="btn btn-sm btn-outline-secondary" onclick="collapseSaveNote()">Save note</button><span id="collapse-saved" class="small text-success" style="display:none;">Saved</span></div>`;
}

function sidebar(d) {
  if (!d.is_dm) return '';
  const s = d.sess;
  const scenes = d.campaign_scenes;
  return html`<div id="sidebar-wrap"><div id="sidebar">
    <div class="sidebar-section-title" data-sb-section="monsters" onclick="sbToggleSection(this)" style="cursor:pointer;" title="Collapse / expand"><span class="sb-caret">&#9662;</span> Monsters &amp; Assets</div>
    <div id="sb-sec-monsters">${d.monsters.length ? d.monsters.map(sm => html`<div class="sidebar-entity" data-entity-type="monster" data-entity-id="${sm.monster_id}">
      <div class="sidebar-entity-row"><span>${sm.display_name}</span><button class="sidebar-btn btn btn-sm py-0 px-1 ${sm.on_map ? 'btn-outline-danger' : 'btn-outline-secondary'}">${sm.on_map ? raw('&#10005;') : '+'}</button></div>
      ${sbHp('monster', sm.monster_id, sm.hp_current, sm.hp_max, sm.hp_pct, sm.on_map)}</div>`) : html`<p class="text-muted small">No monsters in session.</p>`}</div>
    <div class="sidebar-section-title mt-2">Party</div>
    ${d.party.length ? d.party.map(c => html`<div class="sidebar-entity" data-entity-type="player" data-entity-id="${c.character_id}">
      <div class="sidebar-entity-row"><span><span class="presence-dot" data-presence="${c.name}" title="Offline"></span>${c.name}</span>
        ${d.obs_enabled ? html`<button class="obs-view-btn btn btn-sm py-0 px-1 btn-outline-secondary" data-character-id="${c.character_id}" title="Show the map through this character (3D if the map supports it)" onclick="obsViewPlayer(event, this)">&#128065;</button>
          <button class="obs-mapmute-btn btn btn-sm py-0 px-1 btn-outline-secondary" data-character-id="${c.character_id}" data-muted="0" title="Mute this voice on the stream" onclick="obsMuteFromMap(event, this)">&#128266;</button>` : ''}
        <button class="sidebar-btn btn btn-sm py-0 px-1 ${c.on_map ? 'btn-outline-danger' : 'btn-outline-secondary'}">${c.on_map ? raw('&#10005;') : '+'}</button></div>
      ${sbHp('player', c.character_id, c.hp_current, c.hp_max, c.hp_pct, c.on_map)}</div>`) : html`<p class="text-muted small">No party members.</p>`}
    ${scenes.length ? html`<div class="sidebar-section-title mt-3 d-flex justify-content-between align-items-center"><span>Scenes</span><button type="button" class="btn btn-danger btn-sm py-0 px-2" style="font-size:.68rem;text-transform:none;letter-spacing:0;" onclick="mapAllStop()" title="Stop all media &amp; clear the active scene">All Stop</button></div>
      ${s && s.campaign_name ? html`<p class="small text-muted mb-1" style="font-size:.68rem;">${s.campaign_name}</p>` : ''}
      <div id="map-np" style="display:none;margin-bottom:3px;"><div id="map-np-song" style="display:none;font-size:.7rem;padding:1px 6px;border-radius:8px;margin-bottom:3px;background:var(--ttrpg-surface);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div><div id="map-np-video" style="display:none;font-size:.7rem;padding:1px 6px;border-radius:8px;margin-bottom:3px;background:var(--ttrpg-surface);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div></div>
      <div id="map-active-scene-banner" style="display:none;margin-bottom:4px;"><span style="font-size:.7rem;padding:1px 6px;border-radius:8px;background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-accent);">&#9654; <span id="map-active-scene-name"></span></span></div>
      ${scenes.map(sc => html`<button class="map-scene-btn btn btn-sm w-100 mb-1 text-start d-flex align-items-center justify-content-between gap-1" data-scene-id="${sc.scene_ID}" data-scene-name="${sc.sceneName}" onclick="mapActivateScene(this)" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);border:1px solid #444;font-size:.75rem;padding:3px 7px;"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${sc.sceneName}</span>
        ${sc.obs_scene ? html`<span class="map-obs-flag" style="flex:0 0 auto;font-size:.7rem;opacity:${d.obs_links_live ? 1 : 0.35};" title="${d.obs_links_live ? `Also cuts OBS to "${sc.obs_scene}"` : `Mapped to OBS "${sc.obs_scene}", but scene linking is switched OFF on the Broadcast page, so it will not cut`}">&#127909;</span>` : ''}</button>`)}`
    : (s && s.campaign_id ? html`<div class="sidebar-section-title mt-3 d-flex justify-content-between align-items-center"><span>Scenes</span><button type="button" class="btn btn-danger btn-sm py-0 px-2" style="font-size:.68rem;text-transform:none;letter-spacing:0;" onclick="mapAllStop()" title="Stop all media &amp; clear the active scene">All Stop</button></div><p class="small text-muted">No active scenes for this campaign.</p>` : '')}
    <div class="sidebar-section-title mt-3">Volume</div>
    <div class="d-flex align-items-center gap-1 mb-1" style="min-width:0;"><span style="font-size:.7rem;color:var(--ttrpg-accent);flex-shrink:0;">&#128266;</span><input type="range" id="map-vol-slider" min="0" max="100" value="${d.current_vol}" oninput="mapVolChange(this.value)" style="flex:1 1 0;min-width:0;width:0;accent-color:var(--ttrpg-accent);cursor:pointer;"><span id="map-vol-label" style="font-size:.7rem;color:var(--sp-muted);min-width:26px;flex-shrink:0;text-align:right;">${d.current_vol}</span></div>
    <div class="sidebar-section-title mt-3">Hint</div><p class="small text-muted">Drag tokens to move. + places on map, ✕ removes.</p></div></div>`;
}

function stripBar(d) {
  const dm = d.is_dm;
  return html`<div style="display:flex;flex-direction:column;align-items:center;justify-content:space-between;gap:6px;padding:8px 4px;flex-shrink:0;z-index:200;background:var(--ttrpg-surface);border-right:1px solid #444;"><div style="display:flex;flex-direction:column;align-items:center;gap:6px;">
    ${dm ? html`${strip('sb-toggle', 'toggleSidebar()', 'Toggle panel', '&#9664;', 44, '1rem')}${rule()}` : ''}
    ${strip('', 'adjustCellPx(8)', 'Zoom in', '+')}<div id="cell-px-label" style="text-align:center;font-size:.65rem;color:var(--sp-muted);line-height:1.4;">${d.cell_px}px</div>${strip('', 'adjustCellPx(-8)', 'Zoom out', '&minus;')}${rule()}
    ${d.bm3d_available ? html`${strip('bm3d-btn', 'enter3d()', "3D mode — first-person view of this map from a token's position", '3D', 44, '1.1rem')}${dm ? strip('bm-sky-btn', 'bmSkyPick()', 'Sky & weather for 3D mode — time of day, clear/cloudy/rain/snow/storm', 'SKY', 26, '.62rem') : ''}` : ''}
    ${dm ? html`${rule()}${strip('fog-peek-btn', 'toggleFogPeek()', "Reveal what's under the fog (DM only — players always see solid fog). Toggle off to preview the players' view.", '&#128065;', 44, '1.2rem')}${rule()}
      <div style="text-align:center;font-size:.6rem;color:var(--sp-muted);line-height:1.3;" title="Distance per square = 5 × this, in whatever unit the map's legend uses. Tune so the move label matches the legend.">Move&nbsp;scale</div>
      <input type="number" id="move-scale-input" value="${d.bm.movement_scale || 1.0}" step="0.1" min="0.1" max="20" onchange="saveMoveScale(this.value)" style="width:44px;height:30px;text-align:center;border-radius:6px;border:1px solid #555;background:var(--sp-input-bg);color:var(--ttrpg-text);font-size:.85rem;" title="Distance per square = 5 × scale (unit implied by the map legend)">
      ${d.obs_enabled ? html`${rule()}<div style="text-align:center;font-size:.6rem;color:var(--sp-muted);line-height:1.3;" title="Cut OBS to a ScenePlay scene. The lit button is what is on screen now.">OBS</div>
        ${strip('obs-closeup-btn', 'obsToggleCloseups(event)', 'Closeup on one player — pick them by name', '&#128247;', 44, '1.1rem')}
        ${strip('obs-autocam-btn', 'obsToggleAutoCam(this)', 'Auto cameras: swap a player to their card when their feed goes dark, back to camera when it returns', 'CAM<br>&#9889;', 26, '.62rem', 'data-on="0" class="obs-two-line"')}
        ${strip('obs-cardon-btn', 'obsMapCardAll(true)', "Show every player's stat card on the stream instead of their camera", 'CARD<br>ON', 26, '.6rem', 'class="obs-two-line"')}
        ${strip('obs-cardoff-btn', 'obsMapCardAll(false)', 'Release every player back to their camera (cards still stand in for dead feeds)', 'CARD<br>OFF', 26, '.6rem', 'class="obs-two-line"')}
        ${strip('', "obsCut('party', this)", 'Cut to the party scene (G)', '&#128101;', 44, '1.1rem', 'class="obs-cut-btn" data-cut="party"')}
        ${strip('obs-cutmap-btn', "obsCut('map', this)", 'Cut to the battle map (M)', '&#128506;', 44, '1.1rem', 'class="obs-cut-btn" data-cut="map"')}
        ${strip('obs-mapmode-btn', 'obsToggleMapMode()', 'Map on stream: auto (3D when someone moves), 2D, or 3D (V)', 'AUTO', 26, '.6rem')}
        ${strip('', "obsCut('intermission', this)", 'Cut to the intermission card', 'BRB', 26, '.62rem', 'class="obs-cut-btn" data-cut="intermission"')}
        ${strip('', "obsCut('pre', this)", 'Cut to the pre-show card', 'PRE', 26, '.62rem', 'class="obs-cut-btn" data-cut="pre"')}
        ${strip('', "obsCut('post', this)", 'Cut to the post-show card', 'POST', 26, '.62rem', 'class="obs-cut-btn" data-cut="post"')}
        ${rule()}${strip('obs-muteplr-btn', "obsMapMuteAll('players', true)", 'Mute every player on the stream (your DM mic stays live)', 'PLR&nbsp;&#128263;', 26, '.62rem')}
        ${strip('obs-muteall-btn', "obsMapMuteAll('everyone', true)", 'Mute everyone on the stream, including your DM mic', 'ALL&nbsp;&#128263;', 26, '.62rem')}
        ${strip('obs-unmute-btn', "obsMapMuteAll('everyone', false)", 'Unmute everyone on the stream', '&#128266;', 26, '.62rem')}` : ''}` : ''}
  </div></div>`;
}

function viewport(d) {
  const bm = d.bm, px = d.cell_px, dm = d.is_dm;
  const ext = bm.bg_image && bm.bg_image.includes('.') ? bm.bg_image.split('.').pop().toLowerCase() : '';
  const lay = (id, z, extra = '') => html`<svg id="${id}" style="position:absolute;top:0;left:0;width:100%;height:100%;z-index:${z};overflow:visible;pointer-events:none;${raw(extra)}"></svg>`;
  return html`<div id="map-viewport"><div id="map-grid" style="width:${bm.grid_cols * px}px;height:${bm.grid_rows * px}px;">
    ${bm.bg_url ? (bm.bg_is_video ? html`<video id="map-bg" autoplay loop muted playsinline><source src="${bm.bg_url}" type="video/${ext === 'ogv' ? 'ogg' : ext}"></video>` : html`<img id="map-bg" src="${bm.bg_url}" alt="">`) : ''}
    <div id="map-lines" style="background-size:${px}px ${px}px;"></div>
    ${lay('fp-visible-layer', 4)}${dm ? lay('floorplan-layer', 5, 'display:none;') : ''}${lay('effects-layer', 6)}${lay('fog-layer', 12)}
    <div id="fx-draw-overlay" style="position:absolute;top:0;left:0;width:100%;height:100%;z-index:20;display:none;cursor:crosshair;touch-action:none;"></div>
    ${dm ? html`<div id="fp-draw-overlay" style="position:absolute;top:0;left:0;width:100%;height:100%;z-index:21;display:none;cursor:crosshair;touch-action:none;"></div>` : ''}
  </div></div>`;
}

function fxPanel() {
  return html`<div id="fx-panel"><div class="fx-panel-header" id="fx-drag-handle"><span>&#10022; Effects</span><button class="fx-close-btn" onclick="closeFxPanel()">&#10005;</button></div>
    <div class="d-flex gap-1 mb-2" id="fx-shape-btns"><button class="fx-shape-btn active" data-shape="circle" onclick="setFxShape('circle')" title="Circle / Sphere">&#9711;</button><button class="fx-shape-btn" data-shape="cone" onclick="setFxShape('cone')" title="Cone">&#9651;</button><button class="fx-shape-btn" data-shape="line" onclick="setFxShape('line')" title="Line">&#9135;</button><button class="fx-shape-btn" data-shape="square" onclick="setFxShape('square')" title="Square / Cube">&#9633;</button></div>
    <div class="d-flex align-items-center gap-2 mb-2"><label class="fx-label">Size</label><input type="number" id="fx-size" value="20" min="5" step="5" class="form-control form-control-sm" style="width:62px;" oninput="fxSizeFt = Math.max(5, parseInt(this.value)||20); updateFxCellLabel()"><span id="fx-cell-label" class="fx-label">= 4 cells</span></div>
    <div class="mb-2"><div class="fx-label mb-1">Presets</div><div class="d-flex flex-wrap gap-1" id="fx-presets"></div></div>
    ${fxLabelInput('fx-fill-color', 'Fill', '<input type="color" id="fx-fill-color" value="#ff4400" class="fx-color-input" oninput="fxFillColor = this.value">')}
    ${fxLabelInput('fx-opacity', 'Opacity', `<input type="range" id="fx-opacity" min="10" max="100" value="35" style="flex:1;min-width:0;accent-color:var(--ttrpg-accent);" oninput="fxOpacity = parseInt(this.value); document.getElementById('fx-opacity-val').textContent = fxOpacity + '%'"><span id="fx-opacity-val" class="fx-label" style="min-width:32px;text-align:right;">35%</span>`)}
    ${fxLabelInput('fx-border-color', 'Border', '<input type="color" id="fx-border-color" value="#ff8800" class="fx-color-input" oninput="fxBorderColor = this.value">')}
    ${fxLabelInput('fx-label-input', 'Label', '<input type="text" id="fx-label-input" class="form-control form-control-sm" placeholder="e.g. Fireball" maxlength="40" oninput="fxLabel = this.value">')}
    <hr style="border-color:var(--sp-border);margin:6px 0;">
    <div class="d-flex gap-2 mb-2"><button id="fx-draw-btn" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="toggleFxDrawMode()">&#9998; Draw: OFF</button><button class="btn btn-sm btn-outline-danger px-2" onclick="clearAllEffects()" title="Remove all effects">&#128465;</button></div>
    <hr style="border-color:var(--sp-border);margin:8px 0;"><div class="fx-label mb-1" style="letter-spacing:.05em;">&#9608; Cloud of War</div><div class="fx-label mb-1" style="color:#666;font-size:.68rem;">Drag to paint &bull; Eraser to uncover</div>
    <div class="d-flex gap-2 mb-1"><button id="cloud-draw-btn" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="toggleCloudDrawMode()">&#9608; Paint: OFF</button><button id="cloud-erase-btn" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="toggleCloudEraseMode()">&#9711; Erase: OFF</button><button class="btn btn-sm btn-outline-danger px-2" onclick="clearAllClouds()" title="Remove all clouds">&#128465;</button></div>
    <div id="fx-selected" style="display:none;"><hr style="border-color:var(--sp-border);margin:6px 0;"><div class="fx-label mb-1">Selected</div><div id="fx-selected-name" style="color:var(--ttrpg-accent);font-weight:600;font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;"></div><button class="btn btn-sm btn-outline-danger w-100 mt-1" onclick="deleteFxSelected()">&#10005; Delete Effect</button></div></div>`;
}

const TOOLBTN = (id, tool, title, label) => html`<button id="fp-tool-${id}" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="BMFP.setTool('${tool}')" title="${title}">${raw(label)}</button>`;
const opts = list => list.map(([v, l]) => html`<option value="${v}">${l}</option>`);
const FINISH = [['none', '(default)'], ['brick', 'Brick'], ['stone', 'Stone'], ['wood', 'Wood']];
const LIGHTS = [['torch', 'Torch'], ['brazier', 'Brazier'], ['lantern', 'Lantern'], ['candle', 'Candle'], ['glow', 'Magical glow']];
const PROPS = [['Furniture', [['crate', 'Crate'], ['barrel', 'Barrel'], ['table', 'Table'], ['chair', 'Chair'], ['chest', 'Chest'], ['bed', 'Bed'], ['shelf', 'Shelf']]],
  ['Structure', [['pillar', 'Pillar'], ['statue', 'Statue'], ['altar', 'Altar'], ['stairs', 'Stairs'], ['rubble', 'Rubble']]],
  ['Nature & Camp', [['tree', 'Tree'], ['pine', 'Pine tree'], ['dead_tree', 'Dead tree'], ['bush', 'Bush'], ['stump', 'Stump'], ['log', 'Fallen log'], ['boulder', 'Boulder'], ['campfire', 'Campfire'], ['tent', 'Tent'], ['cactus', 'Cactus'], ['well', 'Well'], ['cart', 'Cart']]],
  ['Modern / Sci-fi', [['console', 'Console'], ['wreck', 'Wrecked vehicle'], ['barricade', 'Barricade']]],
  ['Graveyard', [['gravestone', 'Gravestone'], ['grave_cross', 'Grave cross'], ['grave_mound', 'Grave mound'], ['tomb', 'Tomb'], ['coffin', 'Coffin'], ['obelisk', 'Obelisk'], ['mausoleum', 'Mausoleum'], ['iron_fence', 'Iron fence'], ['gallows', 'Gallows']]],
  ['Portals', [['portal_arch', 'Stone arch portal'], ['portal_ring', 'Ring portal'], ['portal_circle', 'Runic circle'], ['portal_mirror', 'Mirror portal'], ['portal_gate', 'Hell gate']]]];

function fpPanel(d) {
  return html`<div id="fp-panel"><div class="fx-panel-header" id="fp-drag-handle"><span>&#9635; Floorplan</span><button class="fx-close-btn" onclick="closeFpPanel()">&#10005;</button></div>
    <div class="fx-label mb-1" style="color:#666;font-size:.68rem;">Walls &amp; doors drawn here are what 3D mode extrudes. Players never see this layer.</div>
    <div class="d-flex align-items-center gap-1 mb-2"><label class="fx-label" for="fp-snap">Snap</label><select id="fp-snap" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setSnap(this.value)" title="Grid snap for drawing — 1 ft allows fine geometry detail; character movement always stays on 5-ft squares"><option value="1">5 ft</option><option value="0.5" selected>2&frac12; ft</option><option value="0.2">1 ft</option></select>
      <button id="fp-undo-btn" class="btn btn-sm btn-outline-secondary px-2" disabled onclick="BMFP.undo()" title="Undo (Ctrl+Z)">&#8630;</button><button id="fp-redo-btn" class="btn btn-sm btn-outline-secondary px-2" disabled onclick="BMFP.redo()" title="Redo (Ctrl+Y)">&#8631;</button></div>
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#9635; Walls</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="d-flex gap-1 mb-2">${TOOLBTN('wall', 'wall', 'Drag to draw a wall line (Shift = straight)', '&#9585; Line')}${TOOLBTN('rect', 'rect', 'Drag corner to corner — a rectangle of four walls', '&#9645; Square')}${TOOLBTN('circle', 'circle', 'Drag from the center outward — a circular ring of walls', '&#9675; Circle')}</div>
      <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label">Height</label><input type="number" id="fp-wall-height" value="10" min="1" max="100" step="5" class="form-control form-control-sm" style="width:62px;" oninput="BMFP.setWallHeight(this.value)"><span class="fx-label">ft</span></div>
      <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label">Texture</label><select id="fp-wall-style" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setWallStyle(this.value)" title="Surface finish for 3D walls and elevation sides — tinted by the map art"><option value="none">Smooth</option><option value="brick">Brick</option><option value="stone">Stone</option><option value="wood">Wood</option></select></div>
      <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label" title="Sky dome for 3D mode — seen past the map's edge and wherever there is no ceiling. Also sets the sun, ambient light and haze.">Sky</label>
        <select id="fp-sky-time" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setSky('time', this.value)" title="Time of day for the 3D sky and its lighting"><option value="">None (dark void)</option><option value="night">Night — stars</option><option value="morning">Morning</option><option value="afternoon">Afternoon</option><option value="evening">Evening</option></select>
        <select id="fp-sky-weather" class="form-select form-select-sm" style="width:auto;flex:0 0 auto;" onchange="BMFP.setSky('weather', this.value)" title="Clear sky, or overcast with drifting cloud and flatter light"><option value="clear">Clear</option><option value="cloudy">Cloudy</option><option value="rain">Rain</option><option value="snow">Snow</option><option value="storm">Storm</option></select></div>
      <div class="form-check" style="margin-bottom:0;"><input class="form-check-input" type="checkbox" id="fp-wall-show" onchange="BMFP.setWallShow(this.checked)"><label class="form-check-label fx-label" for="fp-wall-show" title="New walls also render on the 2D map for players — e.g. to block off art that's wrong (stairs that don't exist)">Players can see new walls (2D)</label></div></div>
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#8645; Elevation</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="d-flex gap-1 mb-1">${TOOLBTN('elev', 'elev', 'Drag a rectangle — it gets the height set below', '&#9645; Square')}${TOOLBTN('elevc', 'elevc', 'Drag from the center outward — it gets the height set below', '&#9675; Circle')}</div>
      <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label">Height</label><input type="number" id="fp-elev-height" value="-10" min="-50" max="100" step="5" class="form-control form-control-sm" style="width:70px;" oninput="BMFP.setElevHeight(this.value)" title="Applied to elevation shapes as you draw them — remembered for next time"><span class="fx-label">ft</span>
        <label class="fx-label">Angle</label><input type="number" id="fp-elev-rot" value="0" min="0" max="359" step="15" class="form-control form-control-sm" style="width:64px;" oninput="BMFP.setElevRot(this.value)" title="Rotation applied to new SQUARE elevations as you draw them (degrees clockwise about the center)"><span class="fx-label">&deg;</span></div>
      <div class="fx-label" style="color:#666;font-size:.68rem;">Negative feet = pit, positive = platform.</div></div>
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#128294; Lights</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="d-flex align-items-center gap-1 mb-1"><button id="fp-tool-light" class="btn btn-sm btn-outline-secondary" onclick="BMFP.setTool('light')" title="Click the map to place a light — 3D renders a glow, a warm pool, and (on Medium/High quality) real flickering light">&#128294; Place</button><select id="fp-light-type" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setLightType(this.value)">${opts(LIGHTS)}</select></div>
      <div class="d-flex align-items-center gap-2"><label class="fx-label" for="fp-light-color">Color</label><input type="color" id="fp-light-color" value="#ff9a3c" class="form-control form-control-sm" style="width:44px;padding:2px;" oninput="BMFP.setLightColor(this.value)" title="Light color — defaults per type"><label class="fx-label" for="fp-light-radius">Reach</label><input type="number" id="fp-light-radius" min="5" max="120" step="5" placeholder="auto" class="form-control form-control-sm" style="width:64px;" oninput="BMFP.setLightRadius(this.value)" title="Light reach in feet — leave blank for the type's default"><span class="fx-label">ft</span></div>
      <div class="fx-label mt-1" style="color:#666;font-size:.68rem;">The erase tool removes lights too.</div></div>
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#129681; Props</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="d-flex align-items-center gap-1 mb-1"><button id="fp-tool-prop" class="btn btn-sm btn-outline-secondary" onclick="BMFP.setTool('prop')" title="Click the map to place a 3D furnishing — solid in 3D: tokens can't step into it (stairs, rubble, and bush stay walkable)">&#129681; Place</button>
        <select id="fp-prop-type" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setPropType(this.value)">${PROPS.map(([g, items]) => html`<optgroup label="${g}">${opts(items)}</optgroup>`)}</select></div>
      <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label" for="fp-prop-rot">Turn</label><input type="number" id="fp-prop-rot" value="0" min="0" max="359" step="45" class="form-control form-control-sm" style="width:64px;" oninput="BMFP.setPropRot(this.value)" title="Rotation in degrees (clockwise)"><label class="fx-label" for="fp-prop-scale">Size</label><input type="number" id="fp-prop-scale" value="1" min="0.25" max="4" step="0.25" class="form-control form-control-sm" style="width:64px;" oninput="BMFP.setPropScale(this.value)" title="Scale multiplier (1 = life size)"><span class="fx-label">&times;</span></div>
      <div class="d-flex align-items-center gap-2"><label class="fx-label" for="fp-prop-texture">Texture</label><select id="fp-prop-texture" class="form-select form-select-sm fp-tex-select" data-empty-label="(default bitmap)" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setPropTexture(this.value)" title="Surface texture for newly placed props — every type has a sensible default bitmap; the Select tool retextures existing ones"></select></div></div>
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#11040; Room Zones</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="d-flex align-items-center gap-1 mb-1"><button class="btn btn-sm btn-outline-primary text-nowrap flex-grow-1" onclick="BMFP.newZone()" title="Start a NEW room, then Paint its floor. Painting without this adds another area to the selected room.">&#43; New room</button><button class="btn btn-sm btn-outline-secondary px-2" onclick="BMFP.deleteZone()" title="Delete the selected room and all its areas">&#128465;</button></div>
      <div class="d-flex align-items-center gap-1 mb-1"><button id="fp-tool-zone" class="btn btn-sm btn-outline-secondary text-nowrap" onclick="BMFP.setTool('zone')" title="Drag rectangles over the SELECTED room's floor — its textures apply to the floor and walls inside. Press + New room first for a new room.">&#9645; Paint</button><select id="fp-zone-sel" class="form-select form-select-sm" style="flex:1;min-width:0;" onchange="BMFP.selectZone(this.value)" disabled title="Selected room — Paint adds areas to it"></select></div>
      <div id="fp-zone-fields" style="display:none;"><input id="fp-zone-name" class="form-control form-control-sm mb-1" maxlength="60" placeholder="room name (e.g. Great Hall)" onchange="BMFP.setZoneField('name', this.value)">
        <div class="small mb-1" style="color:var(--sp-muted);font-size:.7rem;">A room painted inside another room uses its own surfaces (smallest zone wins).</div>
        <div id="fp-zone-rects" class="small mb-1" style="color:var(--sp-muted);" title="Each painted rectangle of this room. Remove one with its &#10005;, or click empty floor inside it with the Erase tool."></div>
        ${[['floor_texture', 'Floor', ''], ['wall_texture', 'Walls', ''], ['ceiling_texture', 'Ceiling', 'data-empty-label="(no ceiling)" title="Roof over this room in 3D — seen from inside; the overhead views look straight through it"']].map(([f, l, x]) => html`<div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label" style="min-width:36px;">${l}</label><select id="fp-zone-${f}" class="form-select form-select-sm fp-tex-select" style="width:auto;flex:1;min-width:0;" ${raw(x)} onchange="BMFP.setZoneField('${f}', this.value)"></select></div>`)}
        <div class="d-flex align-items-center gap-2 mb-1"><label class="fx-label" style="min-width:36px;">Height</label><input type="number" id="fp-zone-ceiling_ft" class="form-control form-control-sm" style="width:72px;flex:0 0 auto;" min="7" max="60" step="0.5" placeholder="ft" onchange="BMFP.setZoneField('ceiling_ft', this.value)" title="Ceiling height in feet above this room's floor (blank = the map's wall height)"><span class="small" style="color:var(--sp-muted);font-size:.7rem;">ft above the floor (blank = wall height)</span></div>
        <div class="d-flex align-items-center gap-2"><label class="fx-label" style="min-width:36px;">Finish</label><select id="fp-zone-wall_style" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;" onchange="BMFP.setZoneField('wall_style', this.value)" title="Procedural finish for walls in this zone without a texture image"><option value="none">(map default)</option><option value="brick">Brick</option><option value="stone">Stone</option><option value="wood">Wood</option></select></div>
        <div class="fx-label mt-1" style="color:#666;font-size:.68rem;">Mis-drawn a rect? Undo removes it.</div></div></div>
    <div class="d-flex gap-1 mb-2">${TOOLBTN('door', 'door', 'Click a wall to turn it into a door; click a door to turn it back', '&#128682; Door')}${TOOLBTN('select', 'select', 'Click a wall, door, prop or light to edit it. Selected props and lights drag to move; the round handle rotates a prop', '&#128269; Select')}${TOOLBTN('erase', 'erase', 'Click a wall / door / elevation / light to delete it', '&#9003; Erase')}</div>
    <div id="fp-sel-box" class="mb-2 p-2" style="display:none;border:1px solid #3df0c8;border-radius:6px;">
      <div class="d-flex align-items-center mb-1"><span id="fp-sel-what" class="fx-label" style="color:#3df0c8;">Wall</span><button class="btn btn-sm btn-outline-danger px-2 ms-auto" onclick="BMFP.deleteSel()" title="Delete the selected wall, door, prop or light">&#128465;</button></div>
      <div class="align-items-center gap-2 mb-1" style="display:flex;" id="fp-sel-hb-row"><label class="fx-label">Height</label><input type="number" id="fp-sel-height" onchange="BMFP.applySel()" min="1" max="100" step="1" placeholder="default" class="form-control form-control-sm" style="width:70px;"><label class="fx-label">Base</label><input type="number" id="fp-sel-base" onchange="BMFP.applySel()" min="-50" max="100" step="1" placeholder="0" class="form-control form-control-sm" style="width:70px;" title="Feet above the floor the wall starts at (bridges, arrow slits)"><span class="fx-label">ft</span></div>
      <div class="align-items-center gap-2 mb-1" style="display:none;" id="fp-sel-prop-row"><label class="fx-label">Turn</label><input type="number" id="fp-sel-rot" onchange="BMFP.applySel()" min="0" max="359" step="45" placeholder="0" class="form-control form-control-sm" style="width:64px;" title="Rotation in degrees (clockwise)"><label class="fx-label">Size</label><input type="number" id="fp-sel-scale" onchange="BMFP.applySel()" min="0.25" max="4" step="0.25" placeholder="1" class="form-control form-control-sm" style="width:64px;" title="Scale multiplier (1 = life size)"><span class="fx-label">&times;</span></div>
      <div class="align-items-center gap-2 mb-1" style="display:none;" id="fp-sel-elev-row"><label class="fx-label">Floor</label><input type="number" id="fp-sel-elev-ft" onchange="BMFP.applySel()" min="-50" max="100" step="5" class="form-control form-control-sm" style="width:70px;" title="Floor height in feet — negative = pit, positive = platform"><span class="fx-label">ft</span><label class="fx-label">Angle</label><input type="number" id="fp-sel-elev-rot" onchange="BMFP.applySel()" min="0" max="359" step="15" placeholder="0" class="form-control form-control-sm" style="width:64px;" title="Rotation in degrees (clockwise, about the rectangle's center)"><span class="fx-label">&deg;</span></div>
      <div class="align-items-center gap-2 mb-1" style="display:none;" id="fp-sel-light-row"><label class="fx-label">Type</label><select id="fp-sel-light-type" onchange="BMFP.applySel()" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;">${opts(LIGHTS)}</select><input type="color" id="fp-sel-light-color" onchange="BMFP.applySel()" class="form-control form-control-sm" style="width:44px;padding:2px;" title="Light color"></div>
      <div class="align-items-center gap-2 mb-1" style="display:none;" id="fp-sel-light-row2"><label class="fx-label">Reach</label><input type="number" id="fp-sel-light-radius" onchange="BMFP.applySel()" min="5" max="120" step="5" placeholder="auto" class="form-control form-control-sm" style="width:56px;" title="Reach in feet"><span class="fx-label">ft</span><label class="fx-label ms-auto" title="Height above the floor, feet">Ht</label><input type="number" id="fp-sel-light-height" onchange="BMFP.applySel()" min="0" max="50" step="1" placeholder="6" class="form-control form-control-sm" style="width:52px;" title="Height above the floor, feet"></div>
      <div class="align-items-center gap-2 mb-1" style="display:none;" id="fp-sel-light-row3"><label class="fx-label" title="Brightness multiplier (1 = normal)">Bright</label><input type="number" id="fp-sel-light-intensity" onchange="BMFP.applySel()" min="0.1" max="3" step="0.1" placeholder="1" class="form-control form-control-sm" style="width:56px;" title="Brightness multiplier, 0.1–3 (1 = normal)"><span class="fx-label">&times;</span><div class="form-check ms-auto" style="margin-bottom:0;" title="Flame flicker in 3D"><input class="form-check-input" type="checkbox" id="fp-sel-light-flicker" onchange="BMFP.applySel()"><label class="form-check-label fx-label" for="fp-sel-light-flicker">Flicker</label></div></div>
      <div class="align-items-center gap-2 mb-1" style="display:flex;" id="fp-sel-tex-row"><label class="fx-label">Texture</label><select id="fp-sel-texture" onchange="BMFP.applySel()" class="form-select form-select-sm fp-tex-select" data-empty-label="(default)" style="width:auto;flex:1;min-width:0;"></select></div>
      <div class="align-items-center gap-2 mb-1" style="display:flex;" id="fp-sel-style-row"><label class="fx-label">Finish</label><select id="fp-sel-style" onchange="BMFP.applySel()" class="form-select form-select-sm" style="width:auto;flex:1;min-width:0;">${opts(FINISH)}</select><div class="form-check" style="margin-bottom:0;"><input class="form-check-input" type="checkbox" id="fp-sel-show" onchange="BMFP.applySel()"><label class="form-check-label fx-label" for="fp-sel-show">2D visible</label></div></div>
      <div class="fx-label" style="opacity:.7;">Changes apply and save automatically.</div></div>
    <hr style="border-color:var(--sp-border);margin:6px 0;">
    <div class="fx-label mb-1" style="letter-spacing:.05em;">&#128065; Player 2D View</div>
    <div class="mb-2 p-2" style="border:1px solid var(--sp-border);border-radius:6px;">
      <div class="form-check" style="margin-bottom:2px;"><input class="form-check-input" type="checkbox" id="fp-show2d-walls" onchange="BMFP.setShow2d('walls', this.checked)"><label class="form-check-label fx-label" for="fp-show2d-walls" title="Players see ALL walls and doors on the 2D map (doors show open/closed live) — saves with the floorplan">Show all walls &amp; doors (2D)</label></div>
      <div class="form-check" style="margin-bottom:0;"><input class="form-check-input" type="checkbox" id="fp-show2d-props" onchange="BMFP.setShow2d('props', this.checked)"><label class="form-check-label fx-label" for="fp-show2d-props" title="Players see all objects as labeled markers on the 2D map — saves with the floorplan">Show objects (2D)</label></div></div>
    <div class="fx-label mb-1">Align &mdash; fit the whole plan to the art</div>
    <div class="d-flex align-items-center gap-1 mb-1">${[[-0.5, 0, 'left', '&#9664;'], [0, -0.5, 'up', '&#9650;'], [0, 0.5, 'down', '&#9660;'], [0.5, 0, 'right', '&#9654;']].map(([x, y, dir, g]) => html`<button class="btn btn-sm btn-outline-secondary px-2 flex-grow-1" onclick="BMFP.nudge(${x}, ${y})" title="Shift the whole floorplan ${dir} ½ square">${raw(g)}</button>`)}</div>
    <div class="d-flex align-items-center gap-1 mb-2"><span class="fx-label" style="min-width:36px;">Scale</span><button class="btn btn-sm btn-outline-secondary px-2 flex-grow-1" onclick="BMFP.scalePlan(1 / 1.05)" title="Shrink the whole floorplan 5% (about its center)">&#8722;</button><button class="btn btn-sm btn-outline-secondary px-2 flex-grow-1" onclick="BMFP.scalePlan(1.05)" title="Grow the whole floorplan 5% (about its center)">&#43;</button></div>
    <div id="fp-status" class="fx-label mb-2">No floorplan yet.</div>
    <div class="d-flex gap-2"><button id="fp-save-btn" class="btn btn-sm btn-ttrpg flex-grow-1" onclick="BMFP.save()" title="Edits autosave about a second after you stop — this saves right now">&#128190; Save now</button>
      ${d.bm3d_available ? html`<button class="btn btn-sm btn-outline-secondary" onclick="fpPreview3dDraft()" title="Open 3D mode showing your UNSAVED edits — exit 3D or save/revert to release the preview">&#128065; 3D</button>` : ''}
      <button class="btn btn-sm btn-outline-secondary" onclick="BMFP.revert()" title="Reload the saved floorplan (drops any edit not yet autosaved)">Revert</button></div>
    <div class="fx-label mt-2" style="color:#666;font-size:.68rem;">With no tool armed, click a door on the map to open / close it.</div></div>`;
}

function dicePanel() {
  return html`<div id="dice-map-panel">
    <div id="dice-drag-handle" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="font-weight:bold;color:var(--ttrpg-accent);"><span class="dice-ico">&#127922;</span> Dice Roller</span><div style="display:flex;gap:4px;"><button id="map-dice-minimize-btn" class="fx-close-btn" onclick="minimizeMapDicePanel()" style="cursor:pointer;" title="Minimize">&#8722;</button><button class="fx-close-btn" onclick="toggleMapDicePanel()" style="cursor:pointer;" title="Close">&#10005;</button></div></div>
    <div class="d-flex flex-wrap gap-1 mb-2">${[4, 6, 8, 10, 12, 20, 100, 2].map(s => html`<button class="btn btn-sm btn-outline-secondary map-dice-btn" data-sides="${s}" onclick="mapSelectDie(${s})">d${s}</button>`)}</div>
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap"><label class="fx-label mb-0">Count</label><div class="d-flex align-items-center" style="gap:2px;"><button class="btn btn-sm btn-outline-secondary px-2 py-0" onclick="stepMapDiceCount(-1)" style="line-height:1.6;">&#8722;</button><input type="number" id="map-dice-count" value="1" min="1" max="20" class="form-control form-control-sm text-center" style="width:52px;"><button class="btn btn-sm btn-outline-secondary px-2 py-0" onclick="stepMapDiceCount(1)" style="line-height:1.6;">&#43;</button></div>
      <div class="btn-group btn-group-sm ms-1"><button id="map-adv-normal" class="btn btn-sm btn-outline-secondary" onclick="mapSetAdvMode('normal')">Normal</button><button id="map-adv-adv" class="btn btn-sm btn-outline-secondary" onclick="mapSetAdvMode('advantage')">Adv</button><button id="map-adv-dis" class="btn btn-sm btn-outline-secondary" onclick="mapSetAdvMode('disadvantage')">Disadv</button></div></div>
    <div class="d-flex align-items-center gap-2 mb-2"><label class="fx-label mb-0">Mod</label><button type="button" class="btn btn-sm btn-outline-secondary" style="min-width:28px;padding:0 6px;" onclick="var i=document.getElementById('map-dice-mod');i.value=(parseInt(i.value)||0)-1">&#8722;</button><input type="number" id="map-dice-mod" value="0" class="form-control form-control-sm text-center" style="width:72px;"><button type="button" class="btn btn-sm btn-outline-secondary" style="min-width:28px;padding:0 6px;" onclick="var i=document.getElementById('map-dice-mod');i.value=(parseInt(i.value)||0)+1">+</button><input type="text" id="map-dice-label" autocomplete="off" class="form-control form-control-sm" placeholder="Label…" style="flex:1;"></div>
    <div id="map-dice-statmods" class="d-flex gap-1 mb-2 flex-wrap" style="display:none;"></div>
    <div id="map-dice-quicklabels" class="d-flex gap-1 mb-2 flex-wrap"></div>
    <div id="map-dice-system-panel" style="display:none;"></div>
    <div class="d-flex align-items-center gap-2 mb-2" id="map-roller-row" style="display:none!important;"><label class="fx-label mb-0" style="flex-shrink:0;">Rolling as</label><select id="map-roller-sel" onchange="mapRollerChanged()" class="form-select form-select-sm" style="flex:1;font-size:.78rem;"></select></div>
    <div id="map-dice-quickref" class="dice-quickref" style="display:none;"></div>
    <div class="d-flex gap-1 mb-2"><button class="btn btn-sm btn-ttrpg flex-grow-1" onclick="mapDoRoll()"><span class="dice-ico">&#127922;</span> Roll</button><button class="btn btn-sm btn-outline-secondary px-2" onclick="mapResetDice()" title="Reset to 1d20 +0">&#8635;</button></div>
    <div id="map-dice-result" style="display:none;margin-bottom:8px;"><div id="map-dice-result-inner" style="background:var(--ttrpg-surface);border:1px solid var(--ttrpg-accent);border-radius:6px;padding:7px 10px;font-size:.85rem;"></div></div>
    <hr style="border-color:var(--sp-border);margin:6px 0;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><span class="fx-label">Roll Feed</span><button class="fx-close-btn" style="font-size:.7rem;" onclick="clearMapDiceFeed()">&#128465;</button></div>
    <div id="map-dice-feed" style="max-height:220px;overflow-y:auto;"><p class="fx-label">No rolls yet.</p></div></div>`;
}

function notesPanel(d) {
  return html`<div id="notes-map-panel">
    <div id="notes-drag-handle" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="font-weight:bold;color:var(--ttrpg-accent);">&#128221; DM Notes <span class="small text-muted">&mdash; ${d.bm.name}</span></span><div style="display:flex;gap:4px;"><button id="map-notes-minimize-btn" class="fx-close-btn" onclick="minimizeMapNotesPanel()" style="cursor:pointer;" title="Minimize">&#8722;</button><button class="fx-close-btn" onclick="toggleMapNotesPanel()" style="cursor:pointer;" title="Close">&#10005;</button></div></div>
    <div id="map-notes-list-view"><button class="btn btn-sm btn-outline-secondary w-100 mb-2" onclick="mapNoteNew()">&#43; New Note</button><div id="map-notes-list" class="d-flex flex-column gap-1"><p class="fx-label mb-0">Loading&#8230;</p></div></div>
    <div id="map-notes-editor" style="display:none;"><input id="map-note-title" maxlength="120" placeholder="Title" class="form-control form-control-sm mb-2"><textarea id="map-note-body" rows="15" placeholder="Write your note&#8230;" class="form-control form-control-sm mb-2" style="resize:vertical;"></textarea>
      <div class="d-flex gap-2 align-items-center"><button class="btn btn-sm btn-ttrpg" onclick="mapNoteSave()">Save</button><button class="btn btn-sm btn-outline-secondary" onclick="mapNotesShowList()" title="Back to the list (saves any changes)">&#8592; Back</button><span id="map-note-status" class="small text-muted ms-auto"></span><button class="btn btn-sm btn-outline-danger" onclick="mapNoteDelete()" title="Delete this note">&#128465;</button></div></div></div>`;
}

function bm3dOverlay(d) {
  const dm = d.is_dm;
  return html`<div id="bm3d-overlay" style="position:fixed;inset:0;z-index:3000;display:none;background:#000;"><canvas id="bm3d-canvas" style="width:100%;height:100%;display:block;"></canvas>
    <div id="bm3d-topbar" style="position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(10,12,18,.82);border-bottom:1px solid #333;">
      <button onclick="exit3d()" style="background:rgba(255,255,255,.08);border:1px solid #e8e6e3;color:#f2f0ec;border-radius:6px;padding:4px 12px;font-size:.85rem;cursor:pointer;white-space:nowrap;">&#10005; Exit 3D</button>
      <select id="bm3d-viewpoint" class="form-select form-select-sm" style="width:auto;${dm ? '' : 'display:none;'}background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:#555;"></select>
      <select id="bm3d-quality" class="form-select form-select-sm" title="Render quality — Low for old machines, High for full atmosphere. Auto-tuned from your frame rate until you pick one." style="width:auto;background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:#555;"><option value="low">✦ Low</option><option value="medium">✦✦ Medium</option><option value="high">✦✦✦ High</option></select>
      ${dm ? html`<button id="bm3d-fog-btn" onclick="bm3dToggleFog()" title="Toggle between your translucent fog and the solid fog players see (tokens inside hidden, blackout from a fogged token's eyes)" style="background:rgba(255,255,255,.08);border:1px solid #777;color:#ccc;border-radius:6px;padding:4px 10px;font-size:.8rem;cursor:pointer;white-space:nowrap;">&#128065; Fog: DM</button>` : ''}
      <span id="bm3d-hint" class="small text-muted flex-grow-1" style="text-align:right;">Click the view to look around &middot; double-click steps <span id="bm3d-step-ft">5 ft</span> where you face &middot; Esc releases the mouse${dm ? raw(' &middot; free fly: hold the mouse button (or W) to fly where you look') : ''}</span></div>
    <div id="bm3d-crosshair" style="position:absolute;left:50%;top:50%;width:10px;height:10px;margin:-5px 0 0 -5px;pointer-events:none;opacity:.7;"><div style="position:absolute;left:4px;top:0;width:2px;height:10px;background:#fff;mix-blend-mode:difference;"></div><div style="position:absolute;left:0;top:4px;width:10px;height:2px;background:#fff;mix-blend-mode:difference;"></div></div></div>`;
}

export function render(d) {
  const dm = d.is_dm;
  return html`<style>${raw(STYLE)}</style>
<div style="margin:-1rem -1rem 0; display:flex; flex-direction:column; height:calc(100dvh - 58px);">
  ${topBar(d)}
  <div id="collapse-banner" class="sp-collapse-banner" style="display:none;"></div>
  ${collapsePanel(d)}
  <div class="d-flex flex-grow-1" style="overflow:hidden;">${sidebar(d)}${stripBar(d)}${viewport(d)}</div>
</div>
${dm ? html`${fxPanel()}${fpPanel(d)}` : ''}
${d.obs_enabled && dm ? html`<div id="obs-closeup-pop" style="display:none;position:fixed;z-index:1200;width:230px;max-height:60vh;overflow-y:auto;padding:8px;border-radius:8px;background:var(--ttrpg-surface,#1b1810);border:1px solid var(--ttrpg-accent,#c9a84c);box-shadow:0 6px 24px rgba(0,0,0,.6);"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;"><span style="font-weight:bold;color:var(--ttrpg-accent);font-size:.78rem;">&#128247; Closeup</span><button onclick="obsCloseCloseups()" title="Close" style="background:none;border:none;color:var(--sp-muted,#8a8371);cursor:pointer;font-size:.9rem;line-height:1;">&#10005;</button></div><div id="obs-closeup-list"></div></div>` : ''}
${dicePanel()}
${dm ? notesPanel(d) : ''}
${d.bm3d_available ? bm3dOverlay(d) : ''}
<div id="tok-tooltip"><div id="tt-layout"><img id="tt-portrait" alt=""><div id="tt-body"><div id="tt-name" style="font-weight:bold;color:var(--ttrpg-accent);margin-bottom:5px;font-size:1rem;"></div>
  <div style="display:flex;justify-content:space-between;gap:16px;font-size:.88rem;margin-bottom:4px;"><span id="tt-hp" style="font-weight:600;"></span><span id="tt-hp-pct" style="padding:1px 7px;border-radius:9px;font-size:.72rem;align-self:center;border:1px solid color-mix(in srgb,var(--ttrpg-text) 30%,transparent);color:color-mix(in srgb,var(--ttrpg-text) 75%,transparent);"></span></div>
  <div id="tt-hp-bar-wrap"><div id="tt-hp-bar"></div></div><div id="tt-speed" style="font-size:.82rem;color:color-mix(in srgb,var(--ttrpg-text) 65%,transparent);margin-bottom:4px;"></div><div id="tt-conditions" style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:4px;"></div><div id="tt-skills" style="color:color-mix(in srgb,var(--ttrpg-text) 65%,transparent);font-size:.8rem;line-height:1.7;"></div></div></div></div>`;
}

export function globals(d) {
  return {
    MAP_ID: d.bm.map_id, CELL_PX: d.cell_px, GRID_COLS: d.bm.grid_cols, GRID_ROWS: d.bm.grid_rows, IS_DM: d.is_dm,
    CURRENT_USER_ID: d.current_user_id, MOVE_SCALE: d.bm.movement_scale || 1.0, MAP_ROLLER_NAME: d.roller_name,
    ROLLER_CHARS: d.roller_chars, GAME_INFO: d.game, SESSION_ID: d.sess ? d.sess.session_id : null,
    COLLAPSE_INIT: d.collapse, FLOORPLAN_VERSION: d.floorplan_version, BM3D_AVAILABLE: d.bm3d_available, OBS_ENABLED: d.obs_enabled,
  };
}

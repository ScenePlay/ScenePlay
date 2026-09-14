// Monsters & Assets library markup (templates/ttrpg/monsters.html); the
// search/detail behaviour is the verbatim inline script (script.js).
import { html } from '../../../lib/dom.js';

const ABS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'];

export function render(d) {
  return html`
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div><h3 style="color:var(--ttrpg-accent);" class="mb-0">Monsters &amp; Assets Library</h3>
    <span class="small text-muted">${d.synced} monster${d.synced !== 1 ? 's' : ''} cached</span></div>
  <div class="d-flex gap-2 flex-wrap align-items-center">
    <a href="/ttrpg/monsters/homebrew/new" class="btn btn-sm btn-outline-secondary">+ Homebrew</a>
    <a href="/ttrpg/reference/settings" class="btn btn-outline-secondary btn-sm" title="Change API source">&#9881; ${d.api_label}</a>
    <button id="sync-btn-monsters" class="btn btn-ttrpg btn-sm" data-action="sync">&#8635; Sync SRD</button></div></div>
<div class="ttrpg-card p-3 mb-3">
  <div class="row g-2 align-items-end">
    <div class="col-sm-3"><label class="form-label small text-muted mb-1">Type</label>
      <select id="filter-type" class="form-select form-select-sm" onchange="doSearch()"><option value="">All Types</option>${d.monster_types.map(t => html`<option value="${t}">${t.charAt(0).toUpperCase() + t.slice(1)}</option>`)}</select></div>
    <div class="col-sm-3"><label class="form-label small text-muted mb-1">Size</label>
      <select id="filter-size" class="form-select form-select-sm" onchange="doSearch()"><option value="">All Sizes</option>${['Tiny', 'Small', 'Medium', 'Large', 'Huge', 'Gargantuan'].map(s => html`<option>${s}</option>`)}</select></div>
    <div class="col-sm-2"><label class="form-label small text-muted mb-1">Source</label>
      <select id="filter-source" class="form-select form-select-sm" onchange="doSearch()"><option value="">All</option><option value="srd">SRD</option><option value="homebrew">Homebrew</option></select></div>
    <div class="col-sm-2 ms-auto"><button class="btn btn-sm btn-outline-secondary w-100" onclick="resetFilters()">Reset Filters</button></div></div>
  <div class="mt-3"><label class="form-label small text-muted mb-1">Challenge Rating: <span id="cr-range-display" style="color:var(--ttrpg-accent);font-weight:600;">CR 0 – 30</span></label>
    <div class="d-flex align-items-center gap-2"><span class="small text-muted" style="min-width:24px;">Min</span>
      <input type="range" id="cr-min-slider" min="0" max="34" value="0" class="form-range flex-grow-1" oninput="syncCrSliders('min')">
      <span class="small text-muted" style="min-width:24px;">Max</span>
      <input type="range" id="cr-max-slider" min="0" max="34" value="34" class="form-range flex-grow-1" oninput="syncCrSliders('max')"></div></div></div>
<div class="row g-3">
  <div class="col-lg-5"><div class="ttrpg-card p-3">
    <div class="mb-3"><input id="search-input" type="text" class="form-control" placeholder="Search by name…" autocomplete="off"></div>
    <div id="search-results" style="max-height:60vh;overflow-y:auto;"><p class="text-muted small">Type to search monsters…</p></div></div></div>
  <div class="col-lg-7">
    <div id="detail-panel" class="ttrpg-card p-3" style="display:none;">
      <div class="d-flex align-items-start gap-3 mb-3 flex-wrap">
        <img id="det-img" src="" alt="" style="width:96px;height:96px;object-fit:contain;border-radius:6px;background:var(--ttrpg-primary);display:none;flex-shrink:0;">
        <div class="flex-grow-1"><h4 id="det-name" style="color:var(--ttrpg-accent);" class="mb-0"></h4><span id="det-meta" class="small text-muted d-block mb-2"></span>
          <div class="d-flex gap-2 flex-wrap"><span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);">CR <span id="det-cr"></span></span>
            <span class="badge bg-secondary">HP <span id="det-hp"></span></span><span class="badge bg-secondary">AC <span id="det-ac"></span></span></div></div></div>
      <div class="row g-1 mb-3 text-center" id="det-abilities" style="display:none;">
        ${ABS.map(ab => html`<div class="col"><div class="ttrpg-card p-1" style="border-color:var(--sp-border);"><div class="small text-muted">${ab}</div>
          <div id="det-${ab.toLowerCase()}" class="fw-bold" style="color:var(--ttrpg-accent);">—</div><div id="det-${ab.toLowerCase()}-mod" class="small text-muted"></div></div></div>`)}</div>
      <div id="det-traits" class="small mb-3"></div>
      <div id="det-actions-wrap" class="mb-3" style="display:none;"><h6 style="color:var(--ttrpg-accent);border-bottom:1px solid var(--sp-border);padding-bottom:4px;">Actions</h6><div id="det-actions" class="small"></div></div>
      <div class="ttrpg-card p-3" style="border-color:var(--sp-border);"><h6 style="color:var(--ttrpg-accent);" class="mb-3">Add to Session</h6>
        <div class="row g-2 align-items-end">
          <div class="col-sm-5"><label class="form-label small text-muted mb-1">Session</label>
            <select id="session-select" class="form-select form-select-sm"><option value="">Select session…</option>${d.sessions.map(s => html`<option value="${s.session_id}">${s.title}</option>`)}</select></div>
          <div class="col-sm-2"><label class="form-label small text-muted mb-1">Count</label><input id="add-count" type="number" min="1" max="20" value="1" class="form-control form-control-sm"></div>
          <div class="col-sm-3"><label class="form-label small text-muted mb-1">HP Override</label><input id="hp-override" type="number" min="1" placeholder="Default" class="form-control form-control-sm"></div>
          <div class="col-sm-2"><button class="btn btn-ttrpg btn-sm w-100" onclick="addToSession()">Add</button></div></div>
        <div id="add-result" class="mt-2 small"></div></div>
      <div id="homebrew-delete-wrap" class="mt-2" style="display:none;">
        <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
          <input type="file" id="hb-img-file" accept="image/png,image/jpeg,image/gif,image/webp" class="form-control form-control-sm" style="max-width:240px;">
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="pasteImageNear(this)" title="Paste image from clipboard">&#128203; Paste</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="uploadMonsterImage()">Set Picture</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="reuseMonsterImage()" title="Reuse a picture already on this server — nothing is copied">&#128444; Choose existing</button>
          <a id="homebrew-edit-link" href="#" class="btn btn-outline-secondary btn-sm">&#9998; Edit</a>
          <span id="hb-img-msg" class="small text-muted"></span></div>
        <form id="homebrew-delete-form" data-api="" data-confirm="Delete this homebrew monster?"><button class="btn btn-outline-danger btn-sm">Delete Homebrew</button></form></div></div>
    <div id="detail-placeholder" class="ttrpg-card p-4 text-center text-muted"><p>Select a monster to view its stat block.</p></div></div></div>`;
}

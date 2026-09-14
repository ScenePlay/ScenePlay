// D&D API settings markup (templates/ttrpg/api_settings.html). The clear
// forms and the settings form carry data-api; the view submits them.
import { html, raw } from '../../../../lib/dom.js';

const CLEAR = '/ttrpg/reference/libraries/clear';
const CONFIRM_SRD = '⚠ WARNING — PLAYER IMPACT\n\nClearing the library unlinks items and spells your players currently have assigned. Their assigned spells lose their details (damage dice, casting time, etc.) and the spell-damage roller will stop working for them until they are re-added.\n\nThis clears all API-synced (SRD) data so it can be re-synced. Your HOMEBREW entries are kept. Characters, sessions, and the monster library are NOT deleted.\n\nClick OK only if you understand players will lose the details of their currently assigned items. Run Sync All afterward to repopulate.';
const CONFIRM_HB = '⚠ WARNING — PLAYER IMPACT\n\nPlayers will lose the details of any currently assigned items/spells that came from your homebrew library (they get unlinked until re-added).\n\nThis deletes ONLY your homebrew (custom) entries. Synced SRD data is kept. This cannot be undone.\n\nClick OK only if you understand and accept this.';
const CONFIRM_ALL = '⚠ FULL WIPE + RESET IDs\n\nDeletes EVERYTHING in all libraries — including your HOMEBREW — and resets IDs to 1.\n\nThen run Sync All: because IDs restart at 1, players assigned items should re-link IF the re-sync produces the same entries in the same order. If it does not match, links can attach to the WRONG item.\n\nCharacters, sessions, and the monster library are not deleted. This cannot be undone. Proceed?';

export function render(d) {
  const current = d.current, opts = d.api_options, known = current in opts;
  return html`<style>
  .api-option { border: 2px solid var(--sp-border); border-radius: 8px; padding: 14px 16px; cursor: pointer; transition: border-color .15s, background .15s; }
  .api-option:hover { border-color: var(--ttrpg-accent); }
  .api-option.selected { border-color: var(--ttrpg-accent); background: color-mix(in srgb, var(--sp-accent) 8%, transparent); }
  .api-option input[type=radio] { display: none; }
  .stat-pill { font-size: .72rem; padding: 2px 7px; border-radius: 10px; background: color-mix(in srgb, var(--sp-primary) 20%, transparent); border: 1px solid var(--sp-border); color: var(--ttrpg-accent); }
  #test-result { font-size: .8rem; }
</style>
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <h3 style="color:var(--ttrpg-accent);" class="mb-0">&#9881; D&amp;D API Settings</h3>
  <div class="d-flex gap-2 flex-wrap">
    <form data-api="${CLEAR}" class="m-0" data-confirm="${CONFIRM_SRD}"><input type="hidden" name="scope" value="srd"><button type="submit" class="btn btn-outline-danger btn-sm">&#128465; Clear SRD</button></form>
    <form data-api="${CLEAR}" class="m-0" data-confirm="${CONFIRM_HB}"><input type="hidden" name="scope" value="homebrew"><button type="submit" class="btn btn-outline-danger btn-sm">&#128465; Clear Homebrew</button></form>
    <form data-api="${CLEAR}" class="m-0" data-confirm="${CONFIRM_ALL}"><input type="hidden" name="scope" value="all"><button type="submit" class="btn btn-danger btn-sm">&#128465; Clear All &amp; Reset IDs</button></form>
    <button id="sync-all-btn" class="btn btn-ttrpg btn-sm" onclick="syncAll()">&#8635; Sync All</button></div></div>
<div class="alert mb-3" style="background:rgba(220,53,69,.1);border:1px solid #dc3545;color:#dc3545;font-size:.82rem;">
  &#9888; <strong>Clearing a library affects players.</strong> Items and spells your players have assigned get unlinked
  &mdash; assigned spells lose their details (damage dice, casting time) and the spell-damage roller stops working for
  them until re-added. You must confirm this in the dialog before clearing.</div>
<div class="ttrpg-card p-3 mb-4"><div class="d-flex align-items-center gap-3 flex-wrap">
  <div><div class="small text-muted mb-1">Currently active API</div><code style="color:var(--ttrpg-accent);font-size:.9rem;">${current}</code></div>
  <div class="ms-auto d-flex align-items-center gap-2"><button class="btn btn-outline-secondary btn-sm" data-current="${current}" onclick="testApi(this.dataset.current)">&#10003; Test Connection</button><span id="test-result" class="text-muted"></span></div></div></div>
<form data-api="/api/v1/reference/settings" id="settings-form">
  <div class="row g-3 mb-4">
    ${Object.entries(opts).map(([url, info]) => html`<div class="col-md-6">
      <label class="api-option d-block ${current === url ? 'selected' : ''}" data-url="${url}" onclick="selectOption(this, this.dataset.url)">
        <input type="radio" name="api_choice" value="${url}" ${current === url ? 'checked' : ''}>
        <div class="d-flex justify-content-between align-items-start mb-2"><span class="fw-bold" style="color:var(--ttrpg-accent);">${info.label}</span>
          ${current === url ? html`<span class="badge" style="background:var(--sp-primary);color:var(--sp-accent);font-size:.65rem;">Active</span>` : ''}</div>
        <code class="small text-muted d-block mb-2">${url === 'merged' ? 'api/2024 first, api/2014 fills the gaps' : url}</code>
        <div class="d-flex gap-2 flex-wrap mb-2"><span class="stat-pill">&#9881; ${info.monsters} monsters</span><span class="stat-pill">&#10022; ${info.feats} feats</span><span class="stat-pill">&#9876; ${info.weapons} weapons</span></div>
        <div class="small text-muted">${info.note}</div></label></div>`)}
    <div class="col-md-6">
      <label class="api-option d-block ${!known ? 'selected' : ''}" onclick="selectOption(this, 'custom')">
        <input type="radio" name="api_choice" value="custom" ${!known ? 'checked' : ''}>
        <div class="fw-bold mb-2" style="color:var(--ttrpg-accent);">Custom URL</div>
        <input type="text" name="custom_url" id="custom-url-input" class="form-control form-control-sm mb-2" value="${!known ? current : ''}" placeholder="https://…/api/…" onclick="event.stopPropagation(); selectOption(this.closest('.api-option'), 'custom')">
        <div class="d-flex align-items-center gap-2"><button type="button" class="btn btn-outline-secondary btn-sm" onclick="event.stopPropagation(); testApi(document.getElementById('custom-url-input').value, 'custom-test-result')">Test</button><span id="custom-test-result" class="small text-muted"></span></div></label></div>
  </div>
  <div class="d-flex gap-3 align-items-center"><button type="submit" class="btn btn-ttrpg">Save Settings</button>
    <div class="small text-muted">&#9888; Changing the API does not automatically re-sync existing libraries. Visit each library page and click <strong>Sync SRD</strong> after saving.</div></div></form>
<div class="ttrpg-card p-3 mt-4"><h6 style="color:var(--ttrpg-accent);" class="mb-3">Endpoint Explorer</h6>
  <div class="d-flex gap-2 mb-2"><input type="text" id="explore-url" class="form-control form-control-sm" value="${current}" placeholder="API base URL">
    <button class="btn btn-outline-secondary btn-sm flex-shrink-0" onclick="testApi(document.getElementById('explore-url').value, 'explore-result')">Fetch</button></div>
  <div id="explore-result" class="small text-muted"></div></div>${raw('')}`;
}

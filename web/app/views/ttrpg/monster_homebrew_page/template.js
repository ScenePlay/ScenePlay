// Homebrew monster/vehicle/asset form (templates/ttrpg/monster_homebrew.html)
// + the token icon prompt modal; behaviour is the verbatim script (script.js).
import { html, raw } from '../../../lib/dom.js';

const SIZES = ['Tiny', 'Small', 'Medium', 'Large', 'Huge', 'Gargantuan'];
const STATS = [['str_val', 'STR', 'strength'], ['dex_val', 'DEX', 'dexterity'], ['con_val', 'CON', 'constitution'], ['int_val', 'INT', 'intelligence'], ['wis_val', 'WIS', 'wisdom'], ['cha_val', 'CHA', 'charisma']];
const sel = (id, extra) => html`<select id="${id}" class="form-select form-select-sm" style="width:auto;background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);" title="${extra}">`;
const kindBtn = (k, label, on) => html`<button type="button" id="hb-kind-${k}" onclick="setHbKind('${k}')" class="btn btn-sm flex-grow-1" style="${on ? 'background:var(--ttrpg-accent);color:var(--sp-on-accent);border:none;' : 'background:var(--ttrpg-surface);color:var(--ttrpg-text);border:1px solid var(--sp-border);'}">${raw(label)}</button>`;

export function render(d) {
  const m = d.m, st = d.stats || {}, isEdit = !!m;
  const curSize = (isEdit ? m.size : '') || 'Medium';
  const curSpeed = (st.speed && st.speed.walk) || '30';
  const genres = Object.entries(d.icon_genres || {});
  const genreOpts = genres.map(([k, g]) => html`<option value="${k}">${g.label}</option>`);
  return html`
<div class="sp-page-head"><h3 style="color:var(--ttrpg-accent);">${isEdit ? 'Edit Homebrew — Monsters & Assets' : 'New Homebrew — Monsters & Assets'}</h3>
  <a href="/ttrpg/monsters" class="btn btn-sm btn-outline-secondary">&larr; Library</a></div>
<div id="hb-error" class="alert alert-danger" style="display:none;"></div>
<form id="hb-form" data-api="${isEdit ? `/ttrpg/monsters/homebrew/${m.template_id}/edit` : '/ttrpg/monsters/homebrew/new'}" data-multipart="1">
  <div class="row g-3">
    <div class="col-12"><div class="d-flex gap-2">${kindBtn('monster', '&#128058; Monster / NPC', true)}${kindBtn('vehicle', '&#128674; Ship / Vehicle', false)}${kindBtn('asset', '&#128230; Other Asset', false)}</div>
      <div class="d-flex align-items-center gap-2 mt-2 flex-wrap">
        ${sel('hb-genre', 'Genre flavor for the randomizer and icon prompt')}${genreOpts}</select>
        ${sel('hb-tier', 'How dangerous / substantial the entry is')}<option value="minion">Minion (CR &frac14;&ndash;2)</option><option value="standard" selected>Standard (CR 2&ndash;6)</option><option value="elite">Elite (CR 7&ndash;11)</option><option value="boss">Boss (CR 12&ndash;17)</option><option value="legendary">Legendary (CR 18&ndash;24)</option></select>
        <button type="button" id="hb-random-btn" class="btn btn-sm" style="background:var(--ttrpg-surface);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);" onclick="randomizeHomebrew()"><span class="dice-ico">&#127922;</span> Randomize</button></div></div>
    <div class="col-12"><div class="ttrpg-card p-3"><h5 style="color:var(--ttrpg-accent);" class="mb-3">Identity</h5><div class="row g-3">
      <div class="col-sm-6"><label class="form-label small text-muted">Name *</label><input type="text" name="name" value="${isEdit ? m.name : ''}" class="form-control" required></div>
      <div class="col-sm-6"><label class="form-label small text-muted">Picture <span class="text-muted">(token art — png/jpg/gif/webp)</span></label>
        <div class="d-flex align-items-center gap-2">
          ${st.image ? html`<img src="${st.image}" alt="" style="width:38px;height:38px;object-fit:cover;border-radius:4px;border:1px solid var(--sp-border);flex-shrink:0;">` : ''}
          <input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp" class="form-control">
          <input type="hidden" name="image_ref" id="hb-image-ref">
          <button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" onclick="pasteImageNear(this)" title="Paste image from clipboard">&#128203; Paste</button>
          <button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" onclick="spPickAsset({kinds:['image'], onPick: it => { document.getElementById('hb-image-ref').value = it.url; const f = document.querySelector('input[type=file][name=image]'); if (f) f.value = ''; spAssetPreview(document.getElementById('hb-image-ref-preview'), it); }})" title="Reuse a picture already on this server — nothing is copied">&#128444; Choose existing</button>
          <span id="hb-image-ref-preview" class="d-inline-flex align-items-center" style="display:none;"></span>
          <button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" onclick="openIconPrompt()" title="Generate an AI image prompt for this token">&#127748; Icon Prompt</button></div>
        ${isEdit && st.image ? html`<div class="form-text text-muted">Leave empty to keep the current picture.</div>` : ''}</div>
      <div class="col-sm-3"><label class="form-label small text-muted">Size</label><select name="size" class="form-select">${SIZES.map(sz => html`<option value="${sz}" ${sz === curSize ? 'selected' : ''}>${sz}</option>`)}</select></div>
      <div class="col-sm-3"><label class="form-label small text-muted">Type</label><input type="text" name="monster_type" placeholder="beast, undead…" value="${isEdit ? m.monster_type : ''}" class="form-control"></div>
      <div class="col-sm-4"><label class="form-label small text-muted">Alignment</label><input type="text" name="alignment" placeholder="chaotic evil…" value="${st.alignment || ''}" class="form-control"></div>
      <div class="col-sm-4"><label class="form-label small text-muted">Speed</label><input type="text" name="speed" value="${curSpeed}" class="form-control"></div>
      <div class="col-sm-2"><label class="form-label small text-muted">CR</label><input type="text" name="cr" value="${isEdit ? m.cr : '1'}" class="form-control"></div>
      <div class="col-sm-2"><label class="form-label small text-muted">XP</label><input type="number" name="xp" value="${st.xp || 0}" min="0" class="form-control"></div></div></div></div>
    <div class="col-md-6"><div class="ttrpg-card p-3"><h5 style="color:var(--ttrpg-accent);" class="mb-3">Combat</h5><div class="row g-3">
      <div class="col-6"><label class="form-label small text-muted">Max HP</label><input type="number" name="hp_max" value="${isEdit ? m.hp_max : 10}" min="1" class="form-control"></div>
      <div class="col-6"><label class="form-label small text-muted">AC</label><input type="number" name="ac" value="${isEdit ? m.ac : 10}" min="1" class="form-control"></div></div></div></div>
    <div class="col-md-6"><div class="ttrpg-card p-3"><h5 style="color:var(--ttrpg-accent);" class="mb-3">Ability Scores</h5><div class="row g-2 text-center">
      ${STATS.map(([stat, label, key]) => html`<div class="col-4 col-sm-2"><label class="form-label small text-muted mb-1">${label}</label><input type="number" name="${stat}" value="${st[key] !== undefined ? st[key] : 10}" min="0" max="30" class="form-control form-control-sm text-center"></div>`)}</div></div></div>
    <div class="col-12"><div class="ttrpg-card p-3"><h5 style="color:var(--ttrpg-accent);" class="mb-3">Additional Info</h5>
      <div class="mb-3"><label class="form-label small text-muted">Languages</label><input type="text" name="languages" placeholder="Common, Draconic…" value="${st.languages || ''}" class="form-control"></div>
      <div><label class="form-label small text-muted">Notes / Special Abilities</label><textarea name="notes" rows="4" class="form-control" placeholder="Describe traits, actions, reactions…">${st.notes || ''}</textarea></div></div></div>
    <div class="col-12 d-flex gap-2"><button type="submit" class="btn btn-ttrpg">${isEdit ? 'Save Changes' : 'Create'}</button><a href="/ttrpg/monsters" class="btn btn-outline-secondary">Cancel</a></div>
  </div></form>

<div class="modal fade" id="iconPromptModal" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-lg modal-dialog-scrollable">
  <div class="modal-content" style="background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-text);">
    <div class="modal-header" style="border-color:var(--ttrpg-accent);"><h5 class="modal-title" style="color:var(--ttrpg-accent);">&#127748; Token Icon Prompt</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <div class="d-flex gap-2 mb-3">
        <button id="icp-topdown-btn" onclick="setIconView('topdown')" class="btn btn-sm flex-grow-1" style="background:var(--ttrpg-accent);color:var(--sp-on-accent);border:none;">&#128676; Top-Down Token <span style="opacity:.75;">(ships, vehicles, objects)</span></button>
        <button id="icp-portrait-btn" onclick="setIconView('portrait')" class="btn btn-sm flex-grow-1" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);border:1px solid var(--sp-border);">&#128058; Creature Portrait <span style="opacity:.75;">(monsters, NPCs)</span></button></div>
      <div class="row g-2 mb-2">
        <div class="col-sm-6"><label class="form-label small text-muted mb-1">Genre</label><select id="icp-genre" class="form-select form-select-sm" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);">${genreOpts}</select></div>
        <div class="col-sm-6"><label class="form-label small text-muted mb-1">Extra Details <span class="text-muted">(optional)</span></label><input type="text" id="icp-freetext" class="form-control form-control-sm" placeholder="e.g. three masts, red sails, kraken figurehead" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);"></div></div>
      <button class="btn btn-ttrpg btn-sm w-100 mb-3" onclick="generateIconPrompt()">&#9889; Generate Prompt</button>
      <div id="icp-output-section" style="display:none;"><hr style="border-color:var(--sp-border);">
        <div class="d-flex align-items-center gap-2 mb-2 flex-wrap"><span class="small text-muted">Paste into your image tool, then upload/paste the result as this entry's Picture.</span>
          <button id="icp-ai-btn" class="btn btn-sm btn-ttrpg ms-auto" style="display:none;font-size:.75rem;" onclick="aiGenerateIcon(this)" title="One click: Gemini generates the token and attaches it to the form's Picture — it saves when you save the entry">&#10024; Generate with Gemini</button>
          <button class="btn btn-sm" style="background:var(--ttrpg-surface);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);font-size:.75rem;" onclick="copyIconPrompt()">&#128203; Copy</button></div>
        <div id="icp-ai-status" class="small mb-2"></div>
        <textarea id="icp-text" class="form-control" readonly style="font-family:monospace;font-size:.78rem;min-height:260px;background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);resize:vertical;"></textarea></div></div>
    <div class="modal-footer" style="border-color:var(--ttrpg-accent);"><span id="icp-copy-fb" style="font-size:.8rem;color:var(--ttrpg-accent);display:none;">Copied!</span><button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Close</button></div></div></div></div>`;
}

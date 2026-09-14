// Edit character (templates/ttrpg/character_edit.html).
import { html, render } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import { loadScripts } from '../../lib/loader.js';
import { suggestBox, dccBlock, bindLibSearch, applyGameSystem, bindTouched } from './_char_form.js';

export const title = 'Edit Character';

export async function mount(outlet, ctx) {
  const id = ctx.params.id;
  const [d] = await Promise.all([api.get(`/api/v1/characters/${id}/edit-options`), loadScripts(['/legacy/paste_image.js', '/legacy/asset_picker.js'])]);
  const c = d.char, dcc = d.dcc, isDcc = c.game_system === 'dcc';
  document.title = `Edit: ${c.name} — ScenePlay`;
  const num = (label, name, val, col = 'col-4 col-sm-2', extra = '') => html`<div class="${col}"><label class="form-label">${label}</label><input type="number" name="${name}" value="${val}" class="form-control" ${extra}></div>`;
  render(outlet, html`<div class="row justify-content-center"><div class="col-md-10 col-lg-8"><div class="ttrpg-card p-4">
    <div class="d-flex justify-content-between align-items-center mb-3"><h3 style="color:var(--ttrpg-accent);">Edit: ${c.name}</h3><a href="/ttrpg/character/${id}" class="btn btn-outline-secondary btn-sm">&#8592; Back</a></div>
    <div class="alert alert-danger" id="ce-error" style="display:none"></div>
    <form id="ce-form" enctype="multipart/form-data">
      <h6 class="text-muted text-uppercase mb-2 mt-1" style="letter-spacing:.08em;">Game system</h6>
      <div class="row g-3 mb-2"><div class="col-sm-6"><select name="game_system" id="gameSystemSel" class="form-select">${Object.entries(d.game_systems).map(([sid, gs]) => html`<option value="${sid}" ${c.game_system === sid ? 'selected' : ''}>${gs.name}</option>`)}</select></div></div>
      <h6 class="text-muted text-uppercase mb-2 mt-1" style="letter-spacing:.08em;">Identity</h6>
      <div class="row g-3">
        <div class="col-sm-6"><label class="form-label">Character Name *</label><input type="text" name="name" value="${c.name}" class="form-control" required autofocus></div>
        <div class="col-sm-3"><label class="form-label">Class</label><div style="position:relative;"><input type="text" name="char_class" id="edit-char-class" value="${c.char_class}" class="form-control" autocomplete="off">${suggestBox('edit-class-suggestions')}</div></div>
        <div class="col-sm-3"><label class="form-label">Race</label><div style="position:relative;"><input type="text" name="race" id="edit-race" value="${c.race}" class="form-control" autocomplete="off">${suggestBox('edit-race-suggestions')}</div></div>
        <div class="col-sm-3"><label class="form-label">Level</label><input type="number" name="level" value="${c.level}" class="form-control" min="1" max="30"></div>
        <div class="col-sm-6"><label class="form-label">Background</label><input type="text" name="background" value="${c.background}" class="form-control"></div>
        <div class="col-sm-3"><label class="form-label">Portrait</label>
          <input type="file" name="portrait" id="edit-portrait-input" class="form-control" accept="image/png,image/jpeg,image/gif,image/webp">
          <input type="hidden" name="portrait_ref" id="edit-portrait-ref">
          <button type="button" class="btn btn-sm btn-outline-secondary mt-1" id="btn-paste" title="Paste image from clipboard">&#128203; Paste</button>
          <button type="button" class="btn btn-sm btn-outline-secondary mt-1" id="btn-pick" title="Reuse a picture already on this server — nothing is copied">&#128444; Choose existing</button>
          <div id="edit-portrait-ref-preview" class="mt-1" style="display:none;"></div>
          ${c.portrait_url ? html`<div class="mt-1"><img src="${c.portrait_url}" style="height:40px;border-radius:4px;" alt="Current portrait"><span class="text-muted small ms-1">current</span></div>` : ''}</div>
      </div>
      <div class="only-5e">
        <h6 class="text-muted text-uppercase mb-2 mt-4" style="letter-spacing:.08em;">Hit Points</h6>
        <div class="row g-3">${num('Current HP', 'hp_current', c.hp_current, 'col-4 col-sm-3', 'min="0"')}${num('Max HP', 'hp_max', c.hp_max, 'col-4 col-sm-3', 'min="0"')}</div>
        <h6 class="text-muted text-uppercase mb-2 mt-4" style="letter-spacing:.08em;">Combat Stats</h6>
        <div class="row g-3">${num('AC', 'ac', c.ac, 'col-4 col-sm-2', 'min="0"')}${num('Speed', 'speed', c.speed, 'col-4 col-sm-2', 'min="0"')}${num('Initiative Bonus', 'initiative_bonus', c.initiative_bonus, 'col-4 col-sm-3')}${num('Passive Perc.', 'passive_perception', c.passive_perception, 'col-4 col-sm-3')}</div>
      </div>
      <h6 class="text-muted text-uppercase mb-2 mt-4" style="letter-spacing:.08em;">Attributes</h6>
      <div class="row g-3">${[['STR', 'str_val'], ['DEX', 'dex_val'], ['CON', 'con_val'], ['INT', 'int_val'], ['WIS', 'wis_val'], ['CHA', 'cha_val']].map(([l, f]) => html`<div class="col-4 col-sm-2${f === 'wis_val' ? ' only-5e' : ''}"><label class="form-label">${l}</label><input type="number" name="${f}" value="${c[f]}" class="form-control text-center" min="1" max="30"></div>`)}</div>
      <h6 class="text-muted text-uppercase mb-2 mt-4" style="letter-spacing:.08em;">Currency</h6>
      <div class="row g-3">${[['Gold', 'gold'], ['Silver', 'silver'], ['Copper', 'copper']].map(([l, f]) => html`<div class="col-4 col-sm-2${f !== 'gold' ? ' only-5e' : ''}"><label class="form-label">${l}</label><input type="number" name="${f}" value="${c[f]}" class="form-control" min="0"></div>`)}</div>
      ${dccBlock(dcc, d.dcc_sizes, !isDcc)}
      <div class="mt-4 d-flex gap-2"><button type="submit" class="btn btn-ttrpg">Save Changes</button><a href="/ttrpg/character/${id}" class="btn btn-outline-secondary">Cancel</a></div>
    </form></div></div></div>`);
  const $ = s => outlet.querySelector(s);
  bindLibSearch(ctx, outlet, { inputs: { class: 'edit-char-class', race: 'edit-race' }, boxes: { class: 'edit-class-suggestions', race: 'edit-race-suggestions' }, systemSel: 'gameSystemSel' });
  bindTouched(ctx, outlet);
  const sel = $('#gameSystemSel'); applyGameSystem(outlet, sel); ctx.on(sel, 'change', () => applyGameSystem(outlet, sel));
  ctx.on($('#btn-paste'), 'click', e => { if (window.pasteImageNear) window.pasteImageNear(e.currentTarget); });
  ctx.on($('#btn-pick'), 'click', () => window.spPickAsset({ kinds: ['image'], onPick: it => { $('#edit-portrait-ref').value = window.spAssetRef(it, 'portraits'); $('#edit-portrait-input').value = ''; window.spAssetPreview($('#edit-portrait-ref-preview'), it); } }));
  ctx.on($('#ce-form'), 'submit', async e => {
    e.preventDefault(); const err = $('#ce-error'); err.style.display = 'none';
    try { await api.upload(`/api/v1/characters/${id}`, new FormData(e.target), { quiet: true }); ctx.navigate(`/ttrpg/character/${id}`); }
    catch (x) { err.textContent = x instanceof ApiError ? x.message : String(x.message || x); err.style.display = ''; }
  });
}

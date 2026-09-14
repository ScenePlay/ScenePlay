// Shared bits for the create / edit character forms: library search boxes,
// game-system switch, DCC crawler block.
import { html } from '../../lib/dom.js';

export const LIB_URLS = { class: '/ttrpg/reference/classes/search', race: '/ttrpg/reference/races/search' };
const escH = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export function suggestBox(id) {
  return html`<div id="${id}" style="display:none;position:absolute;top:100%;left:0;right:0;z-index:300;background:var(--sp-surface);border:1px solid var(--sp-border);border-radius:0 0 6px 6px;max-height:220px;overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.4);min-width:220px;"></div>`;
}

export function dccBlock(dcc, sizes, hidden) {
  return html`<div class="only-dcc" style="${hidden ? 'display:none;' : ''}">
    <h6 class="text-muted mt-4 mb-2 text-uppercase" style="letter-spacing:.08em;">Crawler</h6>
    <div class="small text-muted mb-2">Health is a 10-slot <b>Health Bar</b> (each slot = Con Mod) &mdash; it fills in automatically. Mana = Intelligence. No AC: armor gives <b>DR</b>, and you <b>Evade</b> with d20 + 2 + Dex Mod.</div>
    <div class="row g-3">
      <div class="col-4 col-sm-2"><label class="form-label">Armor DR</label><input type="number" name="dcc_dr" class="form-control" value="${dcc.dr}" min="0"></div>
      <div class="col-4 col-sm-2"><label class="form-label">Move (ft)</label><input type="number" name="dcc_move" class="form-control" value="${dcc.move}" min="0"></div>
      <div class="col-4 col-sm-2"><label class="form-label">Step (ft)</label><input type="number" name="dcc_step" class="form-control" value="${dcc.step}" min="0"></div>
      <div class="col-4 col-sm-2"><label class="form-label">Size</label><select name="dcc_size" class="form-select">${sizes.map(([v, name]) => html`<option value="${v}" ${dcc.size === v ? 'selected' : ''}>${name}</option>`)}</select></div>
      <div class="col-4 col-sm-2"><label class="form-label" title="Starts at Cha Mod × 2">Popularity</label><input type="number" name="dcc_popularity" class="form-control" value="${dcc.popularity}" min="0"></div>
      <div class="col-4 col-sm-2"><label class="form-label">AI Favor</label><input type="number" name="dcc_ai_favor" class="form-control" value="${dcc.ai_favor}" min="0"></div>
      <div class="col-6 col-sm-3"><label class="form-label">Crawler number</label><input type="text" name="dcc_crawler_number" class="form-control" value="${dcc.crawler_number}"></div>
      <div class="col-6 col-sm-3"><label class="form-label">Gender / pronouns</label><input type="text" name="dcc_pronouns" class="form-control" value="${dcc.pronouns}"></div>
      <div class="col-6 col-sm-3"><label class="form-label">Floor entered</label><input type="text" name="dcc_floor_entered" class="form-control" value="${dcc.floor_entered}"></div>
      <div class="col-6 col-sm-3"><label class="form-label" title="3 per Level gained">Stat points to spend</label><input type="number" name="dcc_stat_points" class="form-control" value="${dcc.stat_points}" min="0"></div>
      <div class="col-12 col-md-4"><label class="form-label">Past Trauma</label><textarea name="dcc_past_trauma" rows="2" class="form-control" placeholder="Table 22">${dcc.past_trauma}</textarea></div>
      <div class="col-12 col-md-4"><label class="form-label">Loose Ends</label><textarea name="dcc_loose_ends" rows="2" class="form-control" placeholder="Table 23">${dcc.loose_ends}</textarea></div>
      <div class="col-12 col-md-4"><label class="form-label">Regrets</label><textarea name="dcc_regrets" rows="2" class="form-control" placeholder="Table 24">${dcc.regrets}</textarea></div>
    </div></div>`;
}

// Class / race library suggestion dropdowns (the old editLibSearch/newLibSearch).
export function bindLibSearch(ctx, root, { inputs, boxes, systemSel }) {
  const timers = {};
  const search = (type, q) => {
    clearTimeout(timers[type]);
    const box = root.querySelector('#' + boxes[type]);
    timers[type] = setTimeout(() => {
      const sys = (root.querySelector('#' + systemSel) || {}).value || 'all';
      fetch(LIB_URLS[type] + '?q=' + encodeURIComponent(q) + '&system=' + encodeURIComponent(sys))
        .then(r => r.json()).then(data => {
          const results = Array.isArray(data) ? data : (data.results || []);
          if (!results.length) { box.style.display = 'none'; return; }
          box.innerHTML = results.map((it, i) => {
            let sub = '';
            if (type === 'class') { const saves = it.saving_throws || ''; sub = 'd' + (it.hit_die || '8') + (saves ? ' &middot; Saves: ' + escH(saves) : ''); }
            else { const parts = []; if (it.size) parts.push(escH(it.size)); if (it.speed) parts.push(it.speed + ' ft'); if (it.ability_bonuses) parts.push(escH(it.ability_bonuses)); sub = parts.join(' &middot; '); }
            return `<div class="edit-lib-row px-3 py-2" style="cursor:pointer;" data-pick="${escH(it.name)}"><div style="font-weight:600;color:var(--ttrpg-accent);font-size:.88rem;">${escH(it.name)}</div>${sub ? `<div style="font-size:.75rem;color:var(--sp-muted);">${sub}</div>` : ''}</div>`;
          }).join('');
          box.querySelectorAll('[data-pick]').forEach(el => el.addEventListener('mousedown', () => { root.querySelector('#' + inputs[type]).value = el.dataset.pick; box.style.display = 'none'; }));
          box.style.display = 'block';
        }).catch(() => { box.style.display = 'none'; });
    }, 200);
  };
  for (const type of ['class', 'race']) {
    const inp = root.querySelector('#' + inputs[type]);
    ctx.on(inp, 'input', () => search(type, inp.value));
    ctx.on(inp, 'focus', () => search(type, inp.value));
  }
  ctx.on(document, 'click', e => {
    Object.values(boxes).forEach(id => { const box = root.querySelector('#' + id); if (box && !box.contains(e.target) && !Object.values(inputs).includes(e.target.id)) box.style.display = 'none'; });
  });
}

// Game-system switch: 5e-only fields hide under Dungeon Crawler Carl; DCC block shows.
export function applyGameSystem(root, sel, extra) {
  const dcc = sel.value === 'dcc';
  root.querySelectorAll('.only-5e').forEach(el => { el.style.display = dcc ? 'none' : ''; });
  root.querySelectorAll('.only-dcc').forEach(el => { el.style.display = dcc ? '' : 'none'; });
  root.querySelectorAll('input[name$="_val"]').forEach(inp => {
    inp.max = dcc ? 999 : 30;
    if (dcc && !inp.dataset.touched && (parseInt(inp.value) || 10) === 10 && inp.name !== 'wis_val') inp.value = 3;
    if (!dcc && !inp.dataset.touched && (parseInt(inp.value) || 3) === 3) inp.value = 10;
  });
  const bg = root.querySelector('[name="background"]');
  if (bg) bg.placeholder = dcc ? 'Combat background: Athlete, Gaming Geek, Militant, Outdoorsy…' : 'Soldier, Noble…';
  if (extra) extra(dcc);
}
export function bindTouched(ctx, root) { root.querySelectorAll('input[name$="_val"]').forEach(inp => ctx.on(inp, 'input', () => { inp.dataset.touched = '1'; })); }

export function fileFromBlob(blob, input, name = 'pasted.png') {
  const dt = new DataTransfer(); dt.items.add(new File([blob], name, { type: blob.type || 'image/png' })); input.files = dt.files;
}

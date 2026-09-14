// The nine DM reference library pages (templates/ttrpg/<kind>_library.html):
// one view, a per-kind config for the add form, filters, columns and detail
// rows. Filters live in the query string (deep links / refresh keep them);
// the old form+flash+redirect posts are data-api forms that toast + reload.
import { html, raw, render, esc } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { loadScripts } from '../../../lib/loader.js';
import { startSync } from './_sync.js';

const REF = '/ttrpg/reference';
const SRC_BASIC = [['srd', 'SRD'], ['homebrew', 'Custom']];
const SRC_DCC = [['srd', 'SRD'], ['homebrew', 'Custom'], ['dcc', 'Dungeon Crawler Carl']];
const SRC_BUILTIN = [['srd', 'SRD'], ['homebrew', 'Custom'], ['dcc', 'Built-in DCC']];
const SYSTEM_FILTER = { name: 'system', label: 'Game system', type: 'select', options: [['dnd5e', 'D&D 5e'], ['dcc', 'Dungeon Crawler Carl']] };
const GAME_SYSTEM_FIELD = { name: 'game_system', label: 'Game system', type: 'select', options: [['dnd5e', 'D&D 5e'], ['dcc', 'Dungeon Crawler Carl']], noBlank: true };
const ORD = n => n + (n === 1 ? 'st' : n === 2 ? 'nd' : n === 3 ? 'rd' : 'th');
const EMPTY = raw('<span class="empty-val">—</span>');
const dash = v => (v ? esc(v) : '—');
const pre = (v, cls = 'small') => html`<div class="${cls}" style="white-space:pre-wrap;color:var(--sp-text);">${v}</div>`;
const tags = (v, sep = ', ', cls = 'prop-tag') => v ? raw(String(v).split(sep).filter(s => s.trim()).map(p => `<span class="${cls} me-1">${esc(p.trim())}</span>`).join('')) : '—';
const customBadge = raw('<span class="cat-badge ms-1">Custom</span>');
const dccBadge = raw('<span class="dcc-badge ms-1" title="Built-in Dungeon Crawler Carl entry">DCC</span>');
const srcBadges = r => html`${r.source === 'dcc' ? dccBadge : ''}${r.source === 'homebrew' ? customBadge : ''}`;
const delForm = (url, name, extra = '') => html`<form data-api="${url}" data-confirm="Delete ${name}?" class="flex-shrink-0 d-inline ${extra}"><button class="btn btn-outline-danger btn-sm py-0 px-1">&#10005;</button></form>`;
const caret = raw('<td class="text-center text-muted" style="font-size:.7rem;">&#9660;</td>');

// ── field + form builders ──────────────────────────────────────────────────

function field(f, v) {
  const val = v === undefined || v === null ? (f.value !== undefined ? f.value : '') : v;
  const cls = f.type === 'textarea' || f.type === 'select' ? '' : '';
  const lab = html`<label class="form-label small text-muted mb-1">${f.label}${f.required ? ' *' : ''}</label>`;
  let ctl;
  if (f.type === 'select') {
    ctl = html`<select name="${f.name}" class="form-select form-select-sm" ${f.required ? 'required' : ''}>${f.noBlank ? '' : html`<option value="">${f.blank || '—'}</option>`}${f.options.map(o => { const [ov, ol] = Array.isArray(o) ? o : [o, o]; return html`<option value="${ov}" ${String(ov) === String(val) ? 'selected' : ''}>${ol}</option>`; })}</select>`;
  } else if (f.type === 'textarea') {
    ctl = html`<textarea name="${f.name}" class="form-control form-control-sm" rows="${f.rows || 2}" style="resize:vertical;" placeholder="${f.placeholder || ''}">${val}</textarea>`;
  } else if (f.type === 'pair') {
    ctl = html`<div class="d-flex gap-1">${f.fields.map(p => html`<input type="number" name="${p.name}" value="${v && v[p.name] ? v[p.name] : ''}" class="form-control form-control-sm" placeholder="${p.placeholder}">`)}</div>`;
  } else if (f.type === 'checks') {
    return html`<div style="display:flex;align-items:flex-end;gap:12px;padding-bottom:2px;${f.pad ? 'padding-top:1.6rem;' : ''}">${f.fields.map(c => html`<div class="form-check mb-0"><input class="form-check-input" type="checkbox" name="${c.name}" id="${f.idp}_${c.name}" ${v && v[c.name] ? 'checked' : ''}><label class="form-check-label small" for="${f.idp}_${c.name}">${c.label}</label></div>`)}</div>`;
  } else if (f.type === 'image') {
    return html`<div class="full-width"><label class="form-label small text-muted mb-1">Image</label>
      ${val ? html`<div class="mb-1"><img src="${val}" alt="" style="max-height:64px;max-width:128px;border-radius:4px;border:1px solid var(--sp-border);background:var(--sp-bg);"><span class="small text-muted ms-2">current image</span></div>` : ''}
      <div class="d-flex gap-2 align-items-center flex-wrap">
        <input type="file" name="image_file" accept="image/*" class="form-control form-control-sm" style="max-width:260px;" data-preview="${f.idp}-preview">
        <button type="button" class="btn btn-sm btn-outline-secondary" data-action="paste" title="Paste image from clipboard">&#128203; Paste</button>
        <span class="small text-muted">or URL:</span>
        <input type="text" name="image_url" value="${val || ''}" class="form-control form-control-sm" placeholder="https://…" style="max-width:260px;">
        <button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" data-action="reuse" title="Reuse a picture already on this server — nothing is copied">&#128444; Choose existing</button></div>
      <img id="${f.idp}-preview" src="" alt="" style="display:none;margin-top:6px;max-height:80px;max-width:160px;border-radius:4px;border:1px solid var(--sp-border);"></div>`;
  } else {
    ctl = html`<input type="${f.type || 'text'}" name="${f.name}" value="${val}" class="form-control form-control-sm${cls}" placeholder="${f.placeholder || ''}" ${f.required ? 'required' : ''} ${raw(f.step ? `step="${f.step}"` : '')} ${raw(f.min !== undefined ? `min="${f.min}"` : '')} ${raw(f.max !== undefined ? `max="${f.max}"` : '')}>`;
  }
  return html`<div class="${f.full ? 'full-width' : ''}">${lab}${ctl}</div>`;
}

function formGrid(fields, row, idp) {
  return html`<div class="add-form-grid mb-3">${fields.map(f => field({ ...f, idp: f.idp || idp }, row ? (f.type === 'pair' || f.type === 'checks' ? row : row[f.name]) : undefined))}</div>`;
}

function addForm(k, d) {
  const multipart = k.fields.some(f => f.type === 'image');
  return html`<div id="add-form" class="ttrpg-card p-3 mb-3" style="display:none;">
    <div class="fw-bold mb-3" style="color:var(--ttrpg-accent);">${k.addTitle}</div>
    <form data-api="${k.addApi}" ${multipart ? 'data-multipart="1"' : ''}>
      ${formGrid(k.fields.map(f => (f.name === 'game_system' && d.system === 'dcc') ? { ...f, value: 'dcc' } : f), null, 'add')}
      <div class="d-flex gap-2"><button type="submit" class="btn btn-ttrpg btn-sm">${k.addButton || 'Add to Library'}</button>
        <button type="button" class="btn btn-outline-secondary btn-sm" data-action="toggle-add">Cancel</button></div></form></div>`;
}

function filterBar(k, d) {
  const f = d.filters, any = Object.values(f).some(v => v);
  return html`<div class="ttrpg-card p-3 mb-3"><form id="filter-form" class="row g-2 align-items-end">
    ${k.filters.map(fl => html`<div class="${fl.col || 'col-sm-2'}"><label class="form-label small text-muted mb-1">${fl.label}</label>
      ${fl.type === 'select' ? html`<select name="${fl.name}" class="form-select form-select-sm"><option value="">All</option>${(typeof fl.options === 'function' ? fl.options(d) : fl.options).map(o => { const [ov, ol] = Array.isArray(o) ? o : [o, o]; return html`<option value="${ov}" ${String(f[fl.name] || '') === String(ov) ? 'selected' : ''}>${ol}</option>`; })}</select>`
        : html`<input type="text" name="${fl.name}" value="${f[fl.name] || ''}" class="form-control form-control-sm" placeholder="${fl.placeholder || ''}">`}</div>`)}
    <div class="col-auto"><button type="submit" class="btn btn-ttrpg btn-sm">Filter</button></div>
    ${any ? html`<div class="col-auto"><a href="${REF}/${k.kind}" class="btn btn-outline-secondary btn-sm">Clear</a></div>` : ''}</form></div>`;
}

const restoreDcc = () => html`<div class="mb-2 text-end"><form data-api="${REF}/library/dcc/restore" class="d-inline" data-confirm="Re-add any built-in Dungeon Crawler Carl entries that were deleted? Edited ones are left alone."><button class="btn btn-outline-secondary btn-sm">&#8635; Restore built-in DCC entries</button></form></div>`;

// ── per-kind configs ───────────────────────────────────────────────────────

const WEAPON_FIELDS = [
  { name: 'name', label: 'Name', required: true, placeholder: 'Vorpal Sword' },
  { name: 'weapon_category', label: 'Category', type: 'select', options: ['Simple', 'Martial', 'Magic'] },
  { name: 'weapon_range', label: 'Range', type: 'select', options: ['Melee', 'Ranged'] },
  { name: 'damage_dice', label: 'Damage Dice', placeholder: '1d8' },
  { name: 'damage_type', label: 'Damage Type', placeholder: 'Slashing' },
  { name: 'two_handed_damage_dice', label: 'Versatile Dice', placeholder: '1d10' },
  { name: 'two_handed_damage_type', label: 'Versatile Type', placeholder: 'Slashing' },
  { type: 'pair', label: 'Range / Throw (ft)', fields: [{ name: 'range_normal', placeholder: 'Norm' }, { name: 'range_long', placeholder: 'Long' }] },
  { name: 'cost', label: 'Cost', placeholder: '15 gp' },
  { name: 'weight', label: 'Weight (lb)', type: 'number', step: '0.1' },
  { name: 'mastery', label: 'Mastery', placeholder: 'Sap' },
  { name: 'properties', label: 'Properties', placeholder: 'Finesse, Light, Thrown', full: true },
  { name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'Special abilities, attunement, etc.', full: true },
  { name: 'image_url', type: 'image' },
];
const ARMOR_FIELDS = [
  { name: 'name', label: 'Name', required: true, placeholder: 'e.g. Mithral Shirt' },
  { name: 'armor_category', label: 'Category', type: 'select', options: ['Light', 'Medium', 'Heavy', 'Shield'] },
  { name: 'armor_class_base', label: 'AC Base / Bonus', type: 'number', value: 0 },
  { name: 'max_dex_bonus', label: 'Max DEX Bonus', type: 'number', placeholder: 'blank = unlimited' },
  { name: 'str_minimum', label: 'STR Minimum', type: 'number', value: 0 },
  { name: 'cost', label: 'Cost', placeholder: '500 gp' },
  { name: 'weight', label: 'Weight (lb)', type: 'number', step: '0.1', value: 0 },
  { type: 'checks', fields: [{ name: 'dex_bonus', label: 'Adds DEX' }, { name: 'stealth_disadvantage', label: 'Stealth Disadv.' }] },
  { name: 'properties', label: 'Properties', placeholder: 'e.g. Magical', full: true },
  { name: 'notes', label: 'Notes', type: 'textarea', full: true },
  { name: 'image_url', type: 'image' },
];
const SCHOOLS = ['Abjuration', 'Conjuration', 'Divination', 'Enchantment', 'Evocation', 'Illusion', 'Necromancy', 'Transmutation'];

const KINDS = {
  feats: {
    kind: 'feats', title: 'Feats Library', noun: 'feat', count: t => `${t} feat${t !== 1 ? 's' : ''} stored locally`, addLabel: '+ Custom Feat', addTitle: 'Add Custom Feat', addApi: `${REF}/feats/add`, idKey: 'feat_lib_id',
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'e.g. War Caster' }, { name: 'prerequisites', label: 'Prerequisite', placeholder: 'e.g. Spellcasting ability' }, { name: 'description', label: 'Description', type: 'textarea', rows: 4, placeholder: 'What does this feat do?', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Feat name…', col: 'col-sm-5' }, { name: 'src', label: 'Source', type: 'select', options: SRC_BASIC, col: 'col-sm-3' }],
    note: d => d.total < 5 ? html`<div class="alert alert-warning mb-3"><strong>Note:</strong> The 2014 SRD only includes 1 feat (Grappler). Most D&amp;D feats are in the Player's Handbook. You can add your own feats using the form below.</div>` : '',
    emptyHint: 'No feats stored yet. Click <strong>Sync SRD</strong> to pull from the API, or use <strong>+ Custom Feat</strong> above.',
    cards: (d, k) => d.rows.map(f => html`<div class="ttrpg-card p-3 mb-2 feat-card" style="border-color:var(--sp-border);">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-1"><div><span class="fw-bold" style="color:var(--ttrpg-accent);font-size:1.05rem;">${f.name}</span>
        ${f.source === 'homebrew' ? html`<span class="badge ms-2" style="background:var(--sp-primary);color:var(--sp-accent);font-size:.65rem;">Custom</span>` : ''}
        ${f.prerequisites ? html`<span class="prereq-badge ms-2">Prereq: ${f.prerequisites}</span>` : ''}</div>
        ${f.source === 'homebrew' ? delForm(`${REF}/feats/${f.feat_lib_id}/delete`, f.name) : ''}</div>
      <div class="feat-desc">${f.description}</div></div>`),
  },
  weapons: {
    kind: 'weapons', title: 'Weapons Library', count: t => `${t} weapon${t !== 1 ? 's' : ''}`, addLabel: '+ Custom Weapon', addTitle: 'Add Custom Weapon', addApi: `${REF}/weapons/add`, idKey: 'weapon_lib_id',
    fields: WEAPON_FIELDS, needsPicker: true,
    filters: [{ name: 'q', label: 'Search', placeholder: 'Weapon name…', col: 'col-sm-4' }, { name: 'cat', label: 'Category', type: 'select', options: ['Simple', 'Martial', 'Magic'] }, { name: 'rng', label: 'Range', type: 'select', options: ['Melee', 'Ranged'] },
      { name: 'src', label: 'Source', type: 'select', options: [['srd', 'SRD'], ['srd-magic', 'Magic (SRD)'], ['homebrew', 'Custom'], ['dcc', 'Dungeon Crawler Carl']] }],
    emptyHint: 'No weapons stored yet. Click <strong>Sync SRD</strong> to pull from the API.',
    head: ['<th style="width:36px;"></th>', 'Name', 'Category', 'Damage', 'Versatile', 'Range', 'Cost', 'Wt', 'Properties / Type', 'Mastery', '<th style="width:36px;"></th>'],
    row: w => {
      const id = w.weapon_lib_id, exp = !!(w.properties || w.notes), magic = w.source === 'srd-magic';
      return html`<tr class="data-row" id="row-${id}" ${exp ? html`data-expandable="${id}" title="Click to show the full description"` : ''}>
        <td class="text-center"><button class="btn btn-outline-secondary btn-sm py-0 px-1" data-toggle-edit="${id}" title="Edit">&#9998;</button></td>
        <td><div class="d-flex align-items-center gap-2">${w.image_url ? html`<img src="${w.image_url}" alt="${w.name}" style="width:36px;height:36px;object-fit:contain;border-radius:4px;border:1px solid var(--sp-border);background:var(--sp-bg);cursor:pointer;" data-img-modal="${w.image_url}" data-img-name="${w.name}" title="Click to enlarge">` : ''}
          <div><span style="color:var(--ttrpg-accent);font-weight:600;">${w.name}</span>${magic ? raw('<span class="magic-badge ms-1">Magic</span>') : w.source === 'homebrew' ? customBadge : ''}</div></div></td>
        <td>${w.weapon_category ? html`<span class="cat-badge">${w.weapon_category}</span>` : EMPTY}</td>
        <td>${w.damage_dice ? html`<strong>${w.damage_dice}</strong> <span class="text-muted small">${w.damage_type}</span>` : raw('<span class="empty-val">edit me</span>')}</td>
        <td>${w.two_handed_damage_dice ? html`<span class="text-muted small">${w.two_handed_damage_dice} ${w.two_handed_damage_type}</span>` : '—'}</td>
        <td>${w.weapon_range === 'Ranged' && w.range_normal ? `${w.range_normal}/${w.range_long} ft` : (w.range_normal && w.range_long) ? html`<span class="text-muted small">throw ${w.range_normal}/${w.range_long}</span>` : '—'}</td>
        <td class="text-muted">${dash(w.cost)}</td><td class="text-muted">${w.weight ? w.weight + 'lb' : '—'}</td>
        <td>${w.properties ? (magic ? html`<span class="text-muted small fst-italic">${w.properties.slice(0, 60)}${w.properties.length > 60 ? html`… <span style="color:var(--ttrpg-accent);">&#9660; more</span>` : ''}</span>` : tags(w.properties)) : '—'}</td>
        <td>${w.mastery ? html`<span class="prop-tag" style="color:var(--ttrpg-accent);">${w.mastery}</span>` : '—'}</td>
        <td class="text-center">${delForm(`${REF}/weapons/${id}/delete`, w.name)}</td></tr>
      ${exp ? html`<tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="11">
        ${w.properties ? html`<div class="small text-muted mb-1" style="font-weight:600;">${magic ? 'Description' : 'Properties'}</div>${pre(w.properties, 'small mb-2')}` : ''}
        ${w.notes ? html`<div class="small text-muted mb-1" style="font-weight:600;">Notes</div>${pre(w.notes)}` : ''}</td></tr>` : ''}
      <tr class="edit-row" id="edit-${id}" style="display:none;"><td colspan="11">
        ${magic ? html`<div class="d-flex gap-3 mb-2 flex-wrap">${w.image_url ? html`<img src="${w.image_url}" alt="${w.name}" style="width:80px;height:80px;object-fit:contain;border-radius:6px;border:1px solid var(--sp-border);background:var(--sp-bg);cursor:pointer;flex-shrink:0;" data-img-modal="${w.image_url}" data-img-name="${w.name}">` : ''}
          ${w.notes ? html`<div class="p-2 flex-grow-1" style="background:color-mix(in srgb, var(--sp-accent) 6%, transparent);border-radius:6px;border:1px solid var(--sp-border);"><div class="small text-muted mb-1" style="font-weight:600;">Magic item description</div>${pre(w.notes)}</div>` : ''}</div>` : ''}
        <form data-api="${REF}/weapons/${id}/edit" data-multipart="1">${formGrid(WEAPON_FIELDS, w, 'edit-' + id)}
          <div class="d-flex gap-2"><button type="submit" class="btn btn-ttrpg btn-sm">Save</button><button type="button" class="btn btn-outline-secondary btn-sm" data-toggle-edit="${id}">Cancel</button></div></form></td></tr>`;
    },
  },
  armor: {
    kind: 'armor', title: 'Armor & Shields Library', count: t => `${t} item${t !== 1 ? 's' : ''}`, addLabel: '+ Custom Armor', addTitle: 'Add Custom Armor', addApi: `${REF}/armor/add`, idKey: 'armor_lib_id',
    fields: ARMOR_FIELDS, needsPicker: true,
    filters: [{ name: 'q', label: 'Search', placeholder: 'Armor name…', col: 'col-sm-4' }, { name: 'cat', label: 'Category', type: 'select', options: ['Light', 'Medium', 'Heavy', 'Shield'] }, { name: 'src', label: 'Source', type: 'select', options: SRC_DCC }],
    emptyHint: 'No armor stored yet. Click <strong>Sync SRD</strong> to pull from the API.',
    head: ['<th style="width:36px;"></th>', 'Name', 'Category', 'AC', 'DEX', 'STR Req', 'Stealth', 'Cost', 'Wt', 'Properties', '<th style="width:36px;"></th>'],
    row: a => {
      const id = a.armor_lib_id, exp = !!(a.properties || a.notes);
      return html`<tr class="data-row" id="row-${id}" ${exp ? html`data-expandable="${id}" title="Click to show the full description"` : ''}>
        <td class="text-center"><button class="btn btn-outline-secondary btn-sm py-0 px-1" data-toggle-edit="${id}" title="Edit">&#9998;</button></td>
        <td><div class="d-flex align-items-center gap-2">${a.image_url ? html`<img src="${a.image_url}" alt="${a.name}" style="width:36px;height:36px;object-fit:contain;border-radius:4px;border:1px solid var(--sp-border);background:var(--sp-bg);cursor:pointer;" data-img-modal="${a.image_url}" data-img-name="${a.name}" title="Click to enlarge">` : ''}
          <div><span style="color:var(--ttrpg-accent);font-weight:600;">${a.name}</span>${a.source === 'homebrew' ? customBadge : ''}</div></div></td>
        <td>${a.armor_category ? html`<span class="cat-badge">${a.armor_category}</span>` : EMPTY}</td>
        <td>${a.armor_category === 'Shield' ? html`<span class="text-muted small">+${a.armor_class_base}</span>` : html`<strong>${a.armor_class_base}</strong>`}</td>
        <td>${a.dex_bonus ? html`<span class="prop-tag">${a.max_dex_bonus === null || a.max_dex_bonus === undefined ? '+DEX' : `+DEX (max ${a.max_dex_bonus})`}</span>` : EMPTY}</td>
        <td>${a.str_minimum ? html`<span class="prop-tag">STR ${a.str_minimum}</span>` : '—'}</td>
        <td>${a.stealth_disadvantage ? raw('<span class="warn-tag">Disadv.</span>') : '—'}</td>
        <td class="text-muted">${dash(a.cost)}</td><td class="text-muted">${a.weight ? a.weight + 'lb' : '—'}</td>
        <td>${a.properties ? tags(a.properties) : '—'}</td>
        <td class="text-center">${delForm(`${REF}/armor/${id}/delete`, a.name)}</td></tr>
      ${exp ? html`<tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="11">
        ${a.properties ? html`<div class="small text-muted mb-1" style="font-weight:600;">Properties</div>${pre(a.properties, 'small mb-2')}` : ''}
        ${a.notes ? html`<div class="small text-muted mb-1" style="font-weight:600;">Notes</div>${pre(a.notes)}` : ''}</td></tr>` : ''}
      <tr class="edit-row" id="edit-${id}" style="display:none;"><td colspan="11">
        <form data-api="${REF}/armor/${id}/edit" data-multipart="1">${formGrid(ARMOR_FIELDS, a, 'edit-' + id)}
          <div class="d-flex gap-2"><button type="submit" class="btn btn-ttrpg btn-sm">Save</button><button type="button" class="btn btn-outline-secondary btn-sm" data-toggle-edit="${id}">Cancel</button></div></form></td></tr>`;
    },
  },
  spells: {
    kind: 'spells', title: 'Spells Library', count: t => `${t} spell${t !== 1 ? 's' : ''}`, addLabel: '+ Custom Spell', addTitle: 'Add Custom Spell', addApi: `${REF}/spells/add`, idKey: 'spell_lib_id',
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'Fireball' },
      { name: 'level', label: 'Level', type: 'select', noBlank: true, options: [[0, 'Cantrip'], ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => [i, `${ORD(i)} level`])] },
      { name: 'school', label: 'School', type: 'select', options: SCHOOLS },
      { name: 'casting_time', label: 'Casting Time', placeholder: '1 action' }, { name: 'range_text', label: 'Range', placeholder: '150 feet' },
      { name: 'components', label: 'Components', placeholder: 'V, S, M (bat fur)' }, { name: 'duration', label: 'Duration', placeholder: 'Instantaneous' },
      { name: 'classes_text', label: 'Classes', placeholder: 'Wizard, Sorcerer' },
      { type: 'checks', pad: true, fields: [{ name: 'concentration', label: 'Concentration' }, { name: 'ritual', label: 'Ritual' }] },
      { name: 'description', label: 'Description', type: 'textarea', rows: 3, placeholder: 'Spell effect description…', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Spell name…', col: 'col-sm-4' }, { name: 'level', label: 'Level', type: 'select', options: [[0, 'Cantrip'], ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => [i, `Level ${i}`])] },
      { name: 'school', label: 'School', type: 'select', options: SCHOOLS }, { name: 'src', label: 'Source', type: 'select', options: SRC_BASIC }],
    emptyHint: 'No spells stored yet. Click <strong>Sync SRD</strong> to pull from the API.',
    head: ['<th style="width:30px;"></th>', 'Name', 'Level', 'School', 'Casting Time', 'Classes', 'Source', '<th style="width:60px;"></th>'],
    row: s => {
      const id = s.spell_lib_id;
      return html`<tr class="data-row" id="row-${id}" data-expandable="${id}" style="cursor:pointer;">${caret}
        <td><span style="color:var(--ttrpg-accent);font-weight:600;">${s.name}</span>${s.concentration ? raw('<span class="conc-badge ms-1">C</span>') : ''}${s.ritual ? raw('<span class="ritual-badge ms-1">R</span>') : ''}${s.source === 'homebrew' ? raw('<span class="level-badge ms-1">Custom</span>') : ''}</td>
        <td><span class="level-badge">${s.level === 0 ? 'Cantrip' : ORD(s.level)}</span></td>
        <td>${s.school ? html`<span class="school-badge">${s.school}</span>` : EMPTY}</td>
        <td class="text-muted small">${dash(s.casting_time)}</td><td class="text-muted small">${dash(s.classes_text)}</td><td class="text-muted small">${s.source}</td>
        <td class="text-center">${s.source === 'homebrew' ? delForm(`${REF}/spells/${id}/delete`, s.name) : ''}</td></tr>
      <tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="8"><div class="row g-3"><div class="col-sm-6">
        <div class="d-flex flex-wrap gap-2 mb-2">${s.casting_time ? html`<span class="small"><span class="text-muted">Cast:</span> ${s.casting_time}</span>` : ''}${s.range_text ? html`<span class="small"><span class="text-muted">Range:</span> ${s.range_text}</span>` : ''}${s.duration ? html`<span class="small"><span class="text-muted">Duration:</span> ${s.duration}</span>` : ''}</div>
        ${s.components ? html`<div class="small mb-2"><span class="text-muted">Components:</span> ${s.components}</div>` : ''}
        ${s.concentration || s.ritual ? html`<div class="d-flex gap-2 mb-2">${s.concentration ? raw('<span class="conc-badge">Concentration</span>') : ''}${s.ritual ? raw('<span class="ritual-badge">Ritual</span>') : ''}</div>` : ''}</div>
        <div class="col-sm-6">${s.description ? pre(s.description) : ''}</div></div></td></tr>`;
    },
  },
  skills: {
    kind: 'skills', title: 'Skills Library', count: t => `${t} skill${t !== 1 ? 's' : ''}`, addLabel: '+ Custom Skill', addTitle: 'Add Custom Skill', addApi: `${REF}/skills/add`, idKey: 'skill_lib_id', dcc: true,
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'Lockpicking' }, GAME_SYSTEM_FIELD,
      { name: 'ability_score', label: 'Ability Score', type: 'select', options: ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'] },
      { name: 'description', label: 'Description', type: 'textarea', placeholder: 'What this skill covers… For Dungeon Crawler Carl start with the category: Attack. / Spell. / Utility. / Passive.', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Skill name…', col: 'col-sm-4' }, { name: 'src', label: 'Source', type: 'select', options: SRC_BUILTIN }, SYSTEM_FILTER],
    emptyHint: 'No skills stored yet. Click <strong>Sync SRD</strong> to pull from the API.',
    head: ['<th style="width:30px;"></th>', 'Skill Name', 'Ability Score', 'Source', '<th style="width:60px;"></th>'],
    row: s => html`<tr class="data-row" id="row-${s.skill_lib_id}" data-expandable="${s.skill_lib_id}" style="cursor:pointer;">${caret}
        <td><span style="color:var(--ttrpg-accent);font-weight:600;">${s.name}</span>${srcBadges(s)}</td>
        <td>${s.ability_score ? html`<span class="ability-badge ability-${s.ability_score}">${s.ability_score}</span>` : EMPTY}</td>
        <td class="text-muted small">${s.source}</td>
        <td class="text-center">${['homebrew', 'dcc'].includes(s.source) ? delForm(`${REF}/skills/${s.skill_lib_id}/delete`, s.name) : ''}</td></tr>
      <tr class="detail-row" id="detail-${s.skill_lib_id}" style="display:none;"><td colspan="5">${s.description ? pre(s.description) : raw('<span class="text-muted small fst-italic">No description.</span>')}</td></tr>`,
  },
  races: {
    kind: 'races', title: 'Races Library', count: t => `${t} race${t !== 1 ? 's' : ''}`, addLabel: '+ Custom Race', addTitle: 'Add Custom Race', addApi: `${REF}/races/add`, idKey: 'race_lib_id', dcc: true,
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'Aasimar' }, GAME_SYSTEM_FIELD,
      { name: 'speed', label: 'Speed (ft)', type: 'number', value: 30, min: 0 }, { name: 'size', label: 'Size', type: 'select', options: ['Tiny', 'Small', 'Medium', 'Large'] },
      { name: 'ability_bonuses', label: 'Ability Bonuses', placeholder: '+2 STR, +1 CON  (DCC: +5 DEX, -2 CHA — INT covers wisdom)' }, { name: 'languages', label: 'Languages', placeholder: 'Common, Elvish' },
      { name: 'traits_text', label: 'Traits (one per line)', type: 'textarea', rows: 3, placeholder: 'Darkvision\nFey Ancestry\nTrance\n(DCC: +2 Climbing, +3 Web (Spell), +2 DR, See in total darkness…)', full: true },
      { name: 'description', label: 'Description / Notes', type: 'textarea', placeholder: 'Alignment tendency, lore, etc.', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Race name…', col: 'col-sm-4' }, { name: 'src', label: 'Source', type: 'select', options: SRC_BUILTIN }, SYSTEM_FILTER],
    emptyHint: 'No races stored yet. Click <strong>Sync SRD</strong> to pull from the API.',
    head: ['<th style="width:30px;"></th>', 'Race', 'Size', 'Speed', 'Ability Bonuses', 'Traits', 'Source', '<th style="width:60px;"></th>'],
    row: r => {
      const id = r.race_lib_id, traits = (r.traits_text || '').split('\n').filter(t => t.trim());
      return html`<tr class="data-row" id="row-${id}" data-expandable="${id}" style="cursor:pointer;">${caret}
        <td><span style="color:var(--ttrpg-accent);font-weight:600;">${r.name}</span>${srcBadges(r)}</td>
        <td>${r.size ? html`<span class="size-badge">${r.size}</span>` : EMPTY}</td><td class="text-muted small">${r.speed} ft</td>
        <td>${r.ability_bonuses ? html`<span style="color:var(--ttrpg-accent);font-size:.82rem;">${r.ability_bonuses}</span>` : EMPTY}</td>
        <td>${traits.length ? html`${traits.slice(0, 3).map(t => html`<span class="trait-tag me-1">${t}</span>`)}${traits.length > 3 ? html`<span class="text-muted small">+${traits.length - 3} more</span>` : ''}` : EMPTY}</td>
        <td class="text-muted small">${r.source}</td>
        <td class="text-center">${['homebrew', 'dcc'].includes(r.source) ? delForm(`${REF}/races/${id}/delete`, r.name) : ''}</td></tr>
      <tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="8"><div class="row g-3"><div class="col-sm-5">
        <div class="small mb-2"><span class="text-muted">Speed:</span> ${r.speed} ft &nbsp; ${r.size ? html`<span class="text-muted">Size:</span> ${r.size}` : ''}</div>
        ${r.ability_bonuses ? html`<div class="small mb-2"><span class="text-muted">Ability Bonuses:</span> ${r.ability_bonuses}</div>` : ''}
        ${r.languages ? html`<div class="small mb-2"><span class="text-muted">Languages:</span> ${r.languages}</div>` : ''}
        ${r.description ? html`<div class="small text-muted fst-italic">${r.description}</div>` : ''}</div>
        <div class="col-sm-7">${traits.length ? html`<div class="small text-muted mb-1" style="font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Racial Traits</div><div class="d-flex flex-wrap gap-1">${traits.map(t => html`<span class="trait-tag">${t.trim()}</span>`)}</div>` : ''}</div></div></td></tr>`;
    },
  },
  equipment: {
    kind: 'equipment', title: 'Equipment Library', icon: '&#127978; ', count: t => `${t} items synced`, addLabel: '+ Custom Item', addTitle: 'Add Custom Item', addButton: 'Add Item', addApi: `${REF}/equipment/add`, idKey: 'equipment_lib_id', syncLabel: '&#8635; Sync from API',
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'Rope (50 ft)' }, { name: 'category', label: 'Category', placeholder: 'Adventuring Gear' }, { name: 'subcategory', label: 'Subcategory', placeholder: 'Standard Gear' },
      { name: 'weight', label: 'Weight (lb)', type: 'number', step: '0.1', min: 0, value: 0 }, { name: 'cost', label: 'Cost', placeholder: '1 gp' },
      { name: 'description', label: 'Description', type: 'textarea', placeholder: 'What does this item do?', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Search items…', col: 'col-sm-4' }, { name: 'cat', label: 'Category', type: 'select', options: d => d.categories || [], col: 'col-sm-3' },
      { name: 'src', label: 'Source', type: 'select', options: [['srd', 'SRD'], ['homebrew', 'Homebrew'], ['dcc', 'Dungeon Crawler Carl']] }],
    emptyHint: 'No items yet — sync from the D&amp;D API or add a custom item.',
    head: ['Name', 'Category', 'Weight', 'Cost', 'Source', ''],
    row: it => {
      const id = it.equipment_lib_id, exp = !!it.description;
      return html`<tr class="data-row" id="row-${id}" ${exp ? html`data-expandable="${id}" title="Click to show the full description"` : ''}>
        <td><span style="color:var(--ttrpg-accent);font-weight:600;">${it.name}</span>${it.subcategory ? html`<span class="small text-muted ms-1">(${it.subcategory})</span>` : ''}
          ${exp ? html`<div class="small text-muted mt-1" style="white-space:pre-wrap;">${it.description.slice(0, 180)}${it.description.length > 180 ? html`… <span style="color:var(--ttrpg-accent);">&#9660; more</span>` : ''}</div>` : ''}</td>
        <td class="small text-muted">${dash(it.category)}</td><td class="small text-muted">${it.weight ? it.weight + ' lb' : '—'}</td><td class="small text-muted">${dash(it.cost)}</td>
        <td><span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);">${it.source}</span></td>
        <td class="text-end">${it.source === 'homebrew' ? delForm(`${REF}/equipment/${id}/delete`, it.name) : ''}</td></tr>
      ${exp ? html`<tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="6">${pre(it.description)}</td></tr>` : ''}`;
    },
  },
  classes: {
    kind: 'classes', title: 'Classes Library', count: t => `${t} class${t !== 1 ? 'es' : ''}`, addLabel: '+ Custom Class', addTitle: 'Add Custom Class', addApi: `${REF}/classes/add`, idKey: 'class_lib_id', dcc: true,
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'Blood Hunter' }, GAME_SYSTEM_FIELD,
      { name: 'hit_die', label: 'Hit Die', type: 'select', noBlank: true, value: 8, options: [[6, 'd6'], [8, 'd8'], [10, 'd10'], [12, 'd12']] },
      { name: 'saving_throws', label: 'Saving Throws', placeholder: 'STR, CON' },
      { name: 'spellcasting_ability', label: 'Spellcasting Ability', type: 'select', blank: 'None', options: ['INT', 'WIS', 'CHA'] },
      { name: 'proficiencies', label: 'Proficiencies', placeholder: 'Light armor, Medium armor… (DCC: stat bonuses, e.g. +3 INT, +2 DEX)', full: true },
      { name: 'skill_choices', label: 'Skill Choices', placeholder: 'Choose 2 from Arcana… (DCC: granted skills, one per line: +5 Arcane, +3 Salvage)', full: true },
      { name: 'subclasses', label: 'Subclasses (comma-separated)', placeholder: 'Order of the Profane Soul, Order of the Ghostslayer', full: true },
      { name: 'description', label: 'Description / Notes', type: 'textarea', placeholder: 'Flavor text, source notes, etc.', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Class name…', col: 'col-sm-4' }, { name: 'src', label: 'Source', type: 'select', options: SRC_BUILTIN }, SYSTEM_FILTER],
    emptyHint: 'No classes stored yet. Click <strong>Sync SRD</strong> to pull the 12 core classes from the API.',
    head: d => ['<th style="width:28px;"></th>', 'Class', d.system === 'dcc' ? '—' : 'Hit Die', 'Saving Throws', d.system === 'dcc' ? 'Class type' : 'Subclasses' + (d.system ? '' : ' / Class type'), 'Spellcasting', 'Source', '<th style="width:54px;"></th>'],
    row: c => {
      const id = c.class_lib_id, subs = (c.subclasses || '').split(',').filter(s => s.trim()), dcc = c.game_system === 'dcc';
      return html`<tr class="data-row" id="row-${id}" data-expandable="${id}" style="cursor:pointer;">${caret}
        <td><span style="color:var(--ttrpg-accent);font-weight:600;">${c.name}</span>${srcBadges(c)}</td>
        <td>${c.hit_die ? html`<span class="hd-badge">d${c.hit_die}</span>` : raw('<span class="text-muted small fst-italic">—</span>')}</td>
        <td class="small" style="color:var(--ttrpg-accent);">${dash(c.saving_throws)}</td>
        <td>${subs.length ? html`${dcc ? raw('<span class="text-muted small">Type:</span>') : ''}${subs.slice(0, 3).map(s => html`<span class="sub-tag me-1">${s.trim()}</span>`)}${subs.length > 3 ? html`<span class="text-muted small">+${subs.length - 3} more</span>` : ''}` : raw('<span class="text-muted small fst-italic">—</span>')}</td>
        <td>${c.spellcasting_ability ? html`<span class="spell-badge">${c.spellcasting_ability}</span>` : raw('<span class="text-muted small fst-italic">—</span>')}</td>
        <td class="small text-muted">${c.source}</td>
        <td class="text-center">${['homebrew', 'dcc'].includes(c.source) ? delForm(`${REF}/classes/${id}/delete`, c.name) : ''}</td></tr>
      <tr class="detail-row" id="detail-${id}" style="display:none;"><td colspan="8"><div class="row g-3"><div class="col-sm-5">
        ${dcc ? html`<div class="small mb-2"><span class="text-muted">Stat bonuses:</span> <span style="color:var(--ttrpg-accent);">${dash(c.proficiencies)}</span></div>`
          : html`<div class="small mb-2"><span class="text-muted">Hit Die:</span> <span style="color:var(--ttrpg-accent);">d${c.hit_die}</span> &nbsp;&nbsp; <span class="text-muted">Saves:</span> <span style="color:var(--ttrpg-accent);">${dash(c.saving_throws)}</span></div>`}
        ${c.spellcasting_ability ? html`<div class="small mb-2"><span class="text-muted">Spellcasting:</span> <span class="spell-badge ms-1">${c.spellcasting_ability}</span></div>` : ''}
        ${c.skill_choices ? html`<div class="small mb-2"><span class="text-muted">${dcc ? 'Granted skills:' : 'Skills:'}</span> <span style="color:var(--sp-text);white-space:pre-wrap;">${c.skill_choices}</span></div>` : ''}
        ${c.description ? html`<div class="small text-muted fst-italic mt-1" style="white-space:pre-wrap;">${c.description}</div>` : ''}</div>
        <div class="col-sm-4">${c.proficiencies && !dcc ? html`<div class="small text-muted mb-1" style="font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Proficiencies</div><div class="small" style="color:var(--sp-text);">${c.proficiencies}</div>` : ''}</div>
        <div class="col-sm-3">${subs.length ? html`<div class="small text-muted mb-1" style="font-weight:600;text-transform:uppercase;letter-spacing:.05em;">${dcc ? 'Class type' : 'Subclasses'}</div><div class="d-flex flex-wrap gap-1">${subs.map(s => html`<span class="sub-tag">${s.trim()}</span>`)}</div>` : ''}</div></div></td></tr>`;
    },
  },
  subclasses: {
    kind: 'subclasses', title: 'Subclasses Library', count: t => `${t} subclass${t !== 1 ? 'es' : ''} stored locally — players pick theirs on the character sheet's Reference tab`, addLabel: '+ Homebrew Subclass', addTitle: 'Add Homebrew Subclass', addApi: `${REF}/subclasses/add`, idKey: 'subclass_lib_id',
    syncUrl: `${REF}/sync/run/subclasses`,
    fields: [{ name: 'name', label: 'Name', required: true, placeholder: 'e.g. Way of the Storm' }, { name: 'class_name', label: 'Class', required: true, type: 'select', blank: '— pick a class —', options: [] },
      { name: 'flavor', label: 'Flavor line', placeholder: 'e.g. Primal Path / Arcane Tradition' },
      { name: 'description', label: 'Description', type: 'textarea', rows: 4, placeholder: 'What defines this archetype? (Add its per-level features after saving.)', full: true }],
    filters: [{ name: 'q', label: 'Search', placeholder: 'Subclass name…', col: 'col-sm-4' }, { name: 'cls', label: 'Class', type: 'select', options: d => d.class_names, col: 'col-sm-3' }, { name: 'src', label: 'Source', type: 'select', options: [['srd', 'SRD'], ['homebrew', 'Homebrew']] }],
    emptyHint: 'No subclasses stored yet. Click <strong>Sync SRD</strong> to pull the official archetypes, or add a <strong>Homebrew Subclass</strong> above.',
    cards: (d, k) => d.rows.map(s => { const feats = d.feats_by_sub[s.name.toLowerCase()] || []; return html`<div class="ttrpg-card p-3 mb-2 sub-card" style="border-color:var(--sp-border);">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-1"><div><span class="fw-bold" style="color:var(--ttrpg-accent);font-size:1.05rem;">${s.name}</span><span class="class-badge ms-2">${s.class_name}</span>
        ${s.flavor ? html`<span class="small text-muted fst-italic ms-2">${s.flavor}</span>` : ''}${s.source === 'homebrew' ? html`<span class="badge ms-2" style="background:var(--sp-primary);color:var(--sp-accent);font-size:.65rem;">Homebrew</span>` : ''}</div>
        ${s.source === 'homebrew' ? html`<form data-api="${REF}/subclasses/${s.subclass_lib_id}/delete" data-confirm="Delete ${s.name} and its homebrew features?" class="flex-shrink-0"><button class="btn btn-outline-danger btn-sm py-0 px-1">&#10005;</button></form>` : ''}</div>
      ${s.description ? html`<div class="sub-desc mb-2">${s.description}</div>` : ''}
      <details ${s.source === 'homebrew' ? 'open' : ''}><summary class="small" style="cursor:pointer;color:var(--ttrpg-accent);">Features (${feats.length})</summary>
        ${feats.length ? feats.map(f => html`<div class="feat-row d-flex gap-2 align-items-start"><span class="text-muted small flex-shrink-0" style="min-width:28px;">L${f.level}</span>
          <div class="flex-grow-1"><span style="color:var(--ttrpg-accent);font-weight:600;font-size:.9rem;">${f.name}</span>${f.description ? html`<div class="sub-desc">${f.description}</div>` : ''}</div>
          ${f.source === 'homebrew' ? html`<form data-api="${REF}/features/${f.feature_lib_id}/delete" data-confirm="Delete feature ${f.name}?" class="flex-shrink-0"><button class="btn btn-outline-danger btn-sm py-0 px-1">&#10005;</button></form>` : ''}</div>`)
          : html`<p class="text-muted small fst-italic mb-1 mt-1">No features stored for this subclass yet.</p>`}
        <form data-api="${REF}/subclasses/features/add" class="d-flex gap-2 flex-wrap align-items-end mt-2 pt-2" style="border-top:1px solid var(--sp-border);"><input type="hidden" name="subclass_lib_id" value="${s.subclass_lib_id}">
          <div><label class="form-label small text-muted mb-1">Lvl</label><input type="number" name="level" value="3" min="1" max="20" class="form-control form-control-sm text-center" style="width:60px;"></div>
          <div style="flex:1 1 140px;max-width:220px;"><label class="form-label small text-muted mb-1">Feature name</label><input type="text" name="name" required class="form-control form-control-sm" placeholder="e.g. Storm Strike"></div>
          <div style="flex:2 1 240px;"><label class="form-label small text-muted mb-1">Description</label><input type="text" name="description" class="form-control form-control-sm" placeholder="What it does…"></div>
          <button type="submit" class="btn btn-ttrpg btn-sm">+ Feature</button></form></details></div>`; }),
  },
};

export const KIND_NAMES = Object.keys(KINDS);
export const title = ctx => (KINDS[ctx.params.kind] || {}).title || 'Library';

const STYLE = `<style>
  .lib-table { background: var(--sp-surface); color: var(--sp-text); }
  .lib-table thead th { background: var(--sp-primary); color: var(--sp-accent); border-bottom-color: var(--sp-border); font-size: .8rem; white-space: nowrap; }
  .lib-table td { border-color: var(--sp-border); font-size: .85rem; vertical-align: middle; }
  .lib-table tbody tr.data-row:hover td { background: color-mix(in srgb, var(--sp-accent) 6%, transparent); }
  .lib-table tr.edit-row td { background: var(--sp-bg); border-top: none; padding: 10px 12px; }
  tr.detail-row td { background: var(--sp-bg); border-top: none; padding: 8px 14px 10px; }
  tr.data-row[data-expandable] { cursor: pointer; }
  .cat-badge, .level-badge { font-size: .7rem; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--sp-border); color: var(--ttrpg-accent); background: color-mix(in srgb, var(--sp-primary) 25%, transparent); white-space: nowrap; }
  .dcc-badge { font-size: .7rem; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--sp-border); color: var(--ttrpg-accent); background: color-mix(in srgb, var(--sp-accent) 12%, transparent); }
  .magic-badge { font-size: .7rem; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--sp-border); color: var(--sp-accent); background: color-mix(in srgb, var(--sp-accent) 15%, transparent); }
  .prop-tag, .trait-tag, .sub-tag { font-size: .68rem; padding: 1px 5px; border-radius: 6px; background: color-mix(in srgb, var(--sp-accent) 10%, transparent); border: 1px solid var(--sp-border); color: var(--sp-muted); white-space: nowrap; }
  .warn-tag { font-size: .68rem; padding: 1px 5px; border-radius: 6px; background: color-mix(in srgb, #f59e0b 20%, transparent); border: 1px solid #f59e0b55; color: #f59e0b; white-space: nowrap; }
  .school-badge, .size-badge { font-size: .7rem; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--sp-border); color: var(--sp-muted); background: color-mix(in srgb, var(--sp-accent) 8%, transparent); white-space: nowrap; }
  .conc-badge { font-size: .65rem; padding: 1px 5px; border-radius: 6px; background: color-mix(in srgb, #f59e0b 20%, transparent); border: 1px solid #f59e0b55; color: #f59e0b; }
  .ritual-badge { font-size: .65rem; padding: 1px 5px; border-radius: 6px; background: color-mix(in srgb, #818cf8 20%, transparent); border: 1px solid #818cf855; color: #818cf8; }
  .hd-badge { font-size: .72rem; padding: 2px 7px; border-radius: 8px; background: color-mix(in srgb, var(--sp-accent) 12%, transparent); border: 1px solid var(--sp-border); color: var(--ttrpg-accent); font-weight: 600; }
  .spell-badge { font-size: .7rem; padding: 2px 7px; border-radius: 8px; background: color-mix(in srgb, #7c5cbf 18%, transparent); border: 1px solid #7c5cbf; color: #c0aaff; font-weight: 600; }
  .ability-badge { font-size: .7rem; padding: 1px 7px; border-radius: 8px; border: 1px solid var(--sp-border); font-weight: 700; white-space: nowrap; }
  .ability-STR { color: #ef4444; background: color-mix(in srgb, #ef4444 15%, transparent); } .ability-DEX { color: #22c55e; background: color-mix(in srgb, #22c55e 15%, transparent); }
  .ability-CON { color: #f97316; background: color-mix(in srgb, #f97316 15%, transparent); } .ability-INT { color: #3b82f6; background: color-mix(in srgb, #3b82f6 15%, transparent); }
  .ability-WIS { color: #a78bfa; background: color-mix(in srgb, #a78bfa 15%, transparent); } .ability-CHA { color: #ec4899; background: color-mix(in srgb, #ec4899 15%, transparent); }
  .empty-val { color: var(--sp-muted); font-style: italic; font-size: .8rem; }
  .add-form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
  .add-form-grid .full-width { grid-column: 1 / -1; }
  .feat-card, .sub-card { transition: border-color .15s; } .feat-card:hover, .sub-card:hover { border-color: var(--ttrpg-accent) !important; }
  .feat-desc, .sub-desc { white-space: pre-wrap; font-size: .85rem; color: var(--sp-muted); }
  .prereq-badge, .class-badge { font-size: .72rem; padding: 2px 7px; border-radius: 10px; background: color-mix(in srgb, var(--sp-accent) 14%, transparent); border: 1px solid var(--sp-border); color: var(--ttrpg-accent); }
  .feat-row { border-top: 1px dashed var(--sp-border); padding: 4px 0; }
</style>`;

function page(k, d) {
  const anyFilter = Object.values(d.filters).some(v => v);
  const head = typeof k.head === 'function' ? k.head(d) : k.head;
  const list = k.cards
    ? (d.rows.length ? k.cards(d, k) : null)
    : (d.rows.length ? html`<div class="ttrpg-card p-0 sp-table-scroll"><table class="table table-hover mb-0 lib-table"><thead><tr>${head.map(h => h.startsWith('<th') ? raw(h) : html`<th>${h}</th>`)}</tr></thead><tbody>${d.rows.map(r => k.row(r, d))}</tbody></table></div>` : null);
  return html`${raw(STYLE)}
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <div><h3 style="color:var(--ttrpg-accent);" class="mb-0">${raw(k.icon || '')}${k.title}</h3><span class="small text-muted">${k.count(d.total)}</span></div>
    <div class="d-flex gap-2 align-items-center flex-wrap">
      <button class="btn btn-outline-secondary btn-sm" data-action="toggle-add">${k.addLabel}</button>
      <a href="${REF}/settings" class="btn btn-outline-secondary btn-sm" title="Change API source">&#9881; ${d.api_label}</a>
      <button id="sync-btn-${k.kind}" class="btn btn-ttrpg btn-sm" data-action="sync">${raw(k.syncLabel || '&#8635; Sync SRD')}</button></div></div>
  ${addForm(k, d)}
  ${k.note ? k.note(d) : ''}
  ${k.dcc ? restoreDcc() : ''}
  ${filterBar(k, d)}
  ${list || html`<div class="ttrpg-card p-4 text-center text-muted"><p>${anyFilter ? `No ${k.kind} match your filters.` : raw(k.emptyHint)}</p></div>`}
  <div id="img-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.75);align-items:center;justify-content:center;">
    <div style="max-width:90vw;max-height:90vh;text-align:center;" data-stop="1"><img id="img-modal-src" src="" alt="" style="max-width:100%;max-height:80vh;border-radius:8px;border:2px solid var(--ttrpg-accent);">
      <div id="img-modal-name" style="color:var(--ttrpg-accent);margin-top:8px;font-weight:600;"></div><button class="btn btn-outline-secondary btn-sm mt-2" data-action="img-close">Close</button></div></div>`;
}

export async function mount(outlet, ctx) {
  const k = KINDS[ctx.params.kind];
  if (!k) { render(outlet, html`<div class="alert alert-warning">Unknown library "${ctx.params.kind}".</div>`); return; }
  const qs = new URLSearchParams();
  for (const f of k.filters) if (ctx.query[f.name]) qs.set(f.name, ctx.query[f.name]);
  const [d] = await Promise.all([api.get(`/api/v1/reference/${k.kind}?${qs}`), k.needsPicker ? loadScripts(['/legacy/paste_image.js', '/legacy/asset_picker.js']) : Promise.resolve()]);
  if (k.kind === 'subclasses') k.fields[1].options = d.class_names;
  document.title = `${k.title} — ScenePlay`;
  render(outlet, page(k, d));
  const $ = s => outlet.querySelector(s);
  const toggleDetail = id => { const det = $(`#detail-${id}`); if (!det) return; const open = det.style.display !== 'none'; det.style.display = open ? 'none' : 'table-row'; const row = $(`#row-${id}`); if (row) { row.style.background = open ? '' : 'color-mix(in srgb, var(--sp-accent) 8%, transparent)'; const c = row.querySelector('td:first-child'); if (c && c.textContent.trim() && /[▼▲]/.test(c.textContent)) c.textContent = open ? '▼' : '▲'; } };
  const toggleEdit = id => { const er = $(`#edit-${id}`), dr = $(`#row-${id}`); const open = er.style.display !== 'none'; er.style.display = open ? 'none' : 'table-row'; dr.style.background = open ? '' : 'color-mix(in srgb, var(--sp-accent) 8%, transparent)'; };

  ctx.on(outlet, 'click', e => {
    const act = e.target.closest('[data-action]');
    if (act && outlet.contains(act)) {
      const a = act.dataset.action;
      if (a === 'toggle-add') { const f = $('#add-form'); f.style.display = f.style.display === 'none' ? '' : 'none'; if (f.style.display !== 'none') f.querySelector('[name="name"]').focus(); return; }
      if (a === 'sync') { startSync(ctx, k.kind, k.syncUrl || `${REF}/${k.kind}/sync`, `${REF}/sync/status/${k.kind}`); return; }
      if (a === 'paste') { window.pasteImageNear(act); return; }
      if (a === 'reuse') {
        // "Choose existing": writes the picked file's URL into the sibling image_url input (nothing is copied)
        window.spPickAsset({ kinds: ['image'], onPick: it => { const row = act.parentElement; const url = row.querySelector('input[name=image_url]'); if (url) url.value = it.url; const file = row.querySelector('input[type=file]'); if (file) file.value = ''; const prev = row.parentElement.querySelector('img[id$="-preview"]'); if (prev) { prev.src = it.url; prev.style.display = ''; } } });
        return;
      }
      if (a === 'img-close') { $('#img-modal').style.display = 'none'; return; }
    }
    const im = e.target.closest('[data-img-modal]');
    if (im) { $('#img-modal-src').src = im.dataset.imgModal; $('#img-modal-name').textContent = im.dataset.imgName; $('#img-modal').style.display = 'flex'; return; }
    if (e.target.closest('#img-modal')) { if (!e.target.closest('[data-stop]')) $('#img-modal').style.display = 'none'; return; }
    const te = e.target.closest('[data-toggle-edit]'); if (te) { toggleEdit(te.dataset.toggleEdit); return; }
    const row = e.target.closest('tr.data-row[data-expandable]');
    if (row && !e.target.closest('button, a, form, input, select, textarea, img')) toggleDetail(row.dataset.expandable);
  });
  ctx.on(outlet, 'change', e => {
    const inp = e.target.closest('input[type=file][data-preview]'); if (!inp) return;
    const preview = $('#' + inp.dataset.preview); if (!preview) return;
    if (!inp.files || !inp.files[0]) { preview.style.display = 'none'; return; }
    const reader = new FileReader(); reader.onload = ev => { preview.src = ev.target.result; preview.style.display = ''; }; reader.readAsDataURL(inp.files[0]);
  });
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form'); if (!f) return;
    e.preventDefault();
    if (f.id === 'filter-form') { const p = new URLSearchParams(); for (const [kk, v] of new FormData(f).entries()) if (v) p.set(kk, v); ctx.navigate(`${REF}/${k.kind}${p.toString() ? '?' + p : ''}`); return; }
    if (!f.dataset.api) return;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const btn = f.querySelector('button[type=submit], button:not([type])'); if (btn) btn.disabled = true;
    try {
      const r = f.dataset.multipart ? await api.upload(f.dataset.api, new FormData(f)) : await api.post(f.dataset.api, Object.fromEntries(new FormData(f).entries()));
      if (r && r.message) toast.success(r.message);
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });
}

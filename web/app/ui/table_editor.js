// Generic Grid.js CRUD editor replacing the 11 *_table.html pages.
// Config schema: see views/media/tables/*.js.
import { html, render, esc } from '../lib/dom.js';
import { api } from '../api.js';
import { toast } from './toast.js';
import { spPickOption } from './pick_option.js';
import { fmtDur } from '../lib/format.js';
import { spOpenMediaPicker, spSetPickerBtn, spSmallThumb, shortMediaName } from './media_picker.js';
import { filtersHtml, wireFilters } from './table_filters.js';

const updateUrl = (prev, query) => prev + (prev.indexOf('?') >= 0 ? '&' : '?') + new URLSearchParams(query).toString();

export async function mountTable(outlet, ctx, cfg) {
  const G = window.gridjs;
  const state = { lookups: {}, sel: new Set(), grid: null, filters: null };

  // lookups (id -> label maps + raw items)
  const loadLookup = async (name) => {
    const lk = cfg.lookups && cfg.lookups[name];
    if (!lk) return null;
    if (state.lookups[name]) return state.lookups[name];
    const p = api.get(lk.url, { quiet: true }).then(d => {
      const items = d.data || d;
      const labelOf = typeof lk.label === 'function' ? lk.label : (r => r[lk.label]);
      const map = new Map(items.map(r => [String(r[lk.id]), labelOf(r)]));
      return { items, map, labelOf, idOf: r => r[lk.id] };
    });
    state.lookups[name] = p;
    return p;
  };
  const eager = Object.entries(cfg.lookups || {}).filter(([, lk]) => !lk.lazy).map(([n]) => loadLookup(n));

  if (cfg.filters) state.filters = await api.get('/api/v1/filters', { quiet: true }).catch(() => null);

  render(outlet, html`<div class="sp-page">
    <div class="sp-page-head"><h1>${cfg.title}</h1></div>
    ${state.filters ? filtersHtml(state.filters, cfg.filters) : ''}
    <div class="sp-table-scroll"><div id="table"></div></div>
    <div id="sp-table-extra"></div></div>`);
  const tableDiv = outlet.querySelector('#table');

  await Promise.all(eager);

  const pk = cfg.primeKey;
  const colIndex = {};
  const columns = cfg.cells.map((c, i) => {
    if (c.id) colIndex[c.id] = i;
    const col = { id: c.id || `_c${i}`, name: c.name || c.id || '', sort: c.sort !== undefined ? c.sort : !!c.id };
    if (c.hidden) col.hidden = true;
    const rowId = row => row.cells[0].data;
    const cellVal = (row, id) => { const j = colIndex[id]; return j === undefined ? undefined : row.cells[j].data; };
    switch (c.cell) {
      case 'text':
        col.attributes = (data, row) => (row ? { contentEditable: 'true', 'data-element-id': rowId(row), 'data-column-id': c.id } : {});
        break;
      case 'select': {
        col.formatter = (cellData, row) => {
          const opts = c.options || [];
          let inner = '';
          if (c.lookup && !(c.lazy)) {
            const lk = state.lookups[c.lookup]; let map = null; lk && lk.then && lk.then(v => { map = v; });
            // eager lookups resolved above; read synchronously via cache
            const cached = state._lkc && state._lkc[c.lookup];
            const entries = cached ? Array.from(cached.map.entries()) : [];
            if (c.blank) inner += `<option value="0"></option>`;
            inner += entries.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cellData) ? ' selected' : ''}>${esc(l)}</option>`).join('');
          } else if (c.lookup) {
            const cached = state._lkc && state._lkc[c.lookup];
            const label = cached ? (cached.map.get(String(cellData)) || '') : '';
            inner = `<option value="${esc(cellData ?? 0)}" selected>${esc(label)}</option>`;
          } else {
            inner = opts.map(o => `<option value="${esc(o.value)}"${String(o.value) === String(cellData) ? ' selected' : ''}>${esc(o.label)}</option>`).join('');
          }
          return G.html(`<select class="sp-cell-select" data-field="${esc(c.id)}" data-id="${esc(rowId(row))}" data-lookup="${esc(c.lookup || '')}" data-current="${esc(cellData ?? '')}"${c.lazy ? ' data-lazy="1"' : ''}>${inner}</select>`);
        };
        break;
      }
      case 'mediaPicker':
        col.formatter = (cellData, row) => {
          const cached = state._lkc && state._lkc[c.lookup];
          const it = cached && cellData > 0 ? cached.items.find(x => parseInt(cached.idOf(x)) === parseInt(cellData)) : null;
          const thumb = it ? spSmallThumb(it[c.thumb || 'thumbnail']) : null;
          const label = it ? shortMediaName(cached.labelOf(it)) : (cellData > 0 ? '…' : '— select —');
          return G.html(`<button type="button" class="sp-picker-btn" data-picker="${esc(c.lookup)}" data-field="${esc(c.id)}" data-id="${esc(rowId(row))}" data-current="${esc(cellData ?? 0)}"><img${thumb ? ` src="${esc(thumb)}"` : ' style="display:none"'}><span>${esc(label)}</span></button>`);
        };
        break;
      case 'check':
        col.name = c.name || 'Del'; col.sort = false;
        col.formatter = (cellData, row) => G.html(`<input type="checkbox" class="sp-row-check" data-id="${esc(rowId(row))}"${state.sel.has(String(rowId(row))) ? ' checked' : ''}>`);
        break;
      case 'duration':
        col.formatter = cellData => fmtDur(cellData);
        break;
      case 'link':
        col.formatter = cellData => G.html(cellData ? `<a href="${esc(cellData)}" target="_blank" rel="noopener">${esc(c.text || 'Source URL')}</a>` : '');
        break;
      case 'nameWithMeta':
        col.formatter = (cellData, row) => { const dn = cellVal(row, c.from) || cellData; return G.html(`<span>${esc(dn)}</span>`); };
        break;
      case 'thumbInfo':
        col.formatter = (cellData, row) => cellData ? G.html(`<img src="${esc(cellData)}" loading="lazy" style="height:45px;border-radius:4px;cursor:pointer;" data-meta="${esc(c.mediaType)}" data-id="${esc(rowId(row))}">`) : '';
        break;
      case 'badge':
        col.formatter = (cellData, row) => {
          const cached = state._lkc && state._lkc[c.lookup];
          const entries = cached ? Array.from(cached.map.entries()) : [];
          const inner = (c.blank ? '<option value="0"></option>' : '') + entries.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cellData) ? ' selected' : ''}>${esc(l)}</option>`).join('');
          const err = c.errorFrom ? (cellVal(row, c.errorFrom) || '') : '';
          const sel = `<select class="sp-cell-select" data-field="${esc(c.id)}" data-id="${esc(rowId(row))}">${inner}</select>`;
          return G.html(err ? `<div>${sel}<span title="${esc(err)}" style="cursor:help;color:#dc3545;font-size:1.1em;"> ⚠</span></div>` : sel);
        };
        break;
      case 'html':
        col.formatter = (cellData, row) => { const out = c.render(cellData, row, { rowId: rowId(row), cellVal: id => cellVal(row, id) }); return out ? G.html(out) : ''; };
        break;
      default:
        break;
    }
    return col;
  });

  // resolve lookup caches synchronously for formatters
  state._lkc = {};
  for (const name of Object.keys(cfg.lookups || {})) {
    const lk = cfg.lookups[name];
    if (!lk.lazy) state._lkc[name] = await loadLookup(name);
  }

  const grid = new G.Grid({
    columns,
    server: { url: cfg.endpoints.list, then: r => r.data, total: r => r.total },
    search: { enabled: true, server: { url: (prev, search) => updateUrl(prev, { search }) } },
    sort: { enabled: true, multiColumn: true, server: { url: (prev, cols) => updateUrl(prev, { sort: cols.map(col => (col.direction === 1 ? '+' : '-') + (cfg.cells[col.index] && cfg.cells[col.index].sortId || cfg.cells[col.index].id)) }) } },
    pagination: { enabled: true, server: { url: (prev, page, limit) => updateUrl(prev, { start: page * limit, length: limit }) } },
  }).render(tableDiv);
  state.grid = grid;
  window.spGrid = grid;

  const save = (id, field, value) => api.post(cfg.endpoints.update, { [pk]: id, [field]: value }, { quiet: true }).catch(e => toast.error('Save failed: ' + e.message));
  const reload = () => { grid.forceRender(); ensureToolbar(); };

  // ── toolbar (Add New Row, page extras, Select Page / Delete Selected) ──
  const toolbar = () => {
    const search = tableDiv.querySelector('div.gridjs-search');
    if (!search) return;
    let box = search.parentNode.querySelector('.sp-grid-actions');
    if (box) return;
    box = document.createElement('div'); box.className = 'sp-grid-actions';
    search.insertAdjacentElement('afterend', box);
    if (cfg.endpoints.add) {
      const add = document.createElement('input'); add.type = 'button'; add.className = 'btn btn-primary'; add.value = 'Add New Row';
      add.onclick = () => addRowPrompt();
      box.appendChild(add);
    }
    (cfg.toolbar || []).forEach(b => { const el = document.createElement('input'); el.type = 'button'; el.className = b.className || 'btn btn-outline-primary ms-1'; el.value = b.label; el.onclick = () => b.onClick(ctx, api); box.appendChild(el); });
    if (cfg.endpoints.del) {
      const selBtn = document.createElement('input'); selBtn.type = 'button'; selBtn.className = 'btn btn-secondary'; selBtn.value = 'Select Page';
      selBtn.onclick = () => { const boxes = tableDiv.querySelectorAll('.sp-row-check'); const all = boxes.length > 0 && [...boxes].every(cb => cb.checked); boxes.forEach(cb => { cb.checked = !all; rowCheck(cb); }); };
      const delBtn = document.createElement('input'); delBtn.type = 'button'; delBtn.id = 'spDelSelectedBtn'; delBtn.className = 'btn btn-danger'; delBtn.value = 'Delete Selected (0)'; delBtn.disabled = true;
      delBtn.onclick = deleteSelected;
      box.append(selBtn, delBtn);
      updateDelBtn();
    }
  };
  const updateDelBtn = () => { const b = outlet.querySelector('#spDelSelectedBtn'); if (!b) return; b.value = `Delete Selected (${state.sel.size})`; b.disabled = state.sel.size === 0; };
  const rowCheck = cb => { if (cb.checked) state.sel.add(String(cb.dataset.id)); else state.sel.delete(String(cb.dataset.id)); updateDelBtn(); };
  const deleteSelected = async () => {
    const n = state.sel.size; if (!n) return;
    if (!confirm(`Delete ${n} selected row${n > 1 ? 's' : ''}?`)) return;
    const b = outlet.querySelector('#spDelSelectedBtn'); b.disabled = true; b.value = 'Deleting…';
    let failed = 0;
    for (const id of state.sel) { try { await api.post(cfg.endpoints.del, { [pk]: id }, { quiet: true }); } catch (e) { failed++; } }
    if (failed) toast.error(`${failed} of ${n} deletes failed.`);
    state.sel.clear(); updateDelBtn(); reload();
  };

  // Add New Row with the campaign/scene prompt (site.js spAddRowPrompt).
  async function addRowPrompt() {
    const body = {};
    const f = cfg.addRow;
    if (f && f.dropdownId) {
      const dd = outlet.querySelector('#' + f.dropdownId);
      const id = dd ? parseInt(dd.value, 10) || 0 : 0;
      const cd = f.contextDropdownId && outlet.querySelector('#' + f.contextDropdownId);
      const cdOn = cd ? parseInt(cd.value, 10) || 0 : 0;
      const cdName = cdOn ? cd.options[cd.selectedIndex].text.trim() : '';
      if (id) {
        let label = f.kind + ' "' + dd.options[dd.selectedIndex].text.trim() + '"';
        if (cdOn) label += ' (' + f.contextKind + ' "' + cdName + '")';
        if (confirm('Add the new row to the currently selected ' + label + '?')) body[f.field] = id;
        else if (f.confirmSkip && !confirm('Create the new row with no ' + f.kind + ' instead? (Cancel adds nothing.)')) return;
        else body[f.field] = 0;
      } else if (cdOn && dd) {
        const opts = Array.from(dd.options).filter(o => parseInt(o.value, 10) || 0);
        if (opts.length) {
          if (confirm('Add the new row to the currently selected ' + f.contextKind + ' "' + cdName + '"?')) {
            const picked = await spPickOption('Add to ' + f.contextKind + ' "' + cdName + '"',
              'Rows here join a ' + f.contextKind + ' through their ' + f.kind + '. Which ' + f.kind + ' should the new row belong to?',
              f.kind.charAt(0).toUpperCase() + f.kind.slice(1), opts.map(o => ({ value: o.value, label: o.text.trim() })));
            if (picked === null) return;
            body[f.field] = parseInt(picked, 10) || 0;
          } else body[f.field] = 0;
        }
      }
    }
    try { await api.post(cfg.endpoints.add, body, { quiet: true }); } catch (e) { toast.error('Add row failed: ' + e.message); }
    reload();
  }

  // Grid.js rebuilds its header on every render (and 'ready' can fire before
  // the search box exists), so poll briefly after each render like the old
  // restoreGridControls() did.
  function ensureToolbar() {
    let tries = 0;
    const t = setInterval(() => {
      if (tableDiv.querySelector('div.gridjs-search')) { clearInterval(t); toolbar(); }
      else if (++tries > 40) clearInterval(t);
    }, 50);
    ctx.cleanup(() => clearInterval(t));
  }
  grid.on('ready', () => { ensureToolbar(); if (cfg.onReady) cfg.onReady(tableDiv, state); });
  ensureToolbar();

  // ── cell editing (contentEditable) ──
  let savedValue;
  ctx.on(tableDiv, 'focusin', ev => { if (ev.target.tagName === 'TD') savedValue = ev.target.textContent; });
  ctx.on(tableDiv, 'focusout', ev => {
    if (ev.target.tagName === 'TD' && ev.target.dataset.elementId) {
      if (savedValue !== ev.target.textContent) save(ev.target.dataset.elementId, ev.target.dataset.columnId, ev.target.textContent);
      savedValue = undefined;
    }
  });
  ctx.on(tableDiv, 'keydown', ev => {
    if (ev.target.tagName === 'TD') {
      if (ev.key === 'Escape') { ev.target.textContent = savedValue; ev.target.blur(); }
      else if (ev.key === 'Enter') { ev.preventDefault(); ev.target.blur(); }
    }
  });
  // selects / checkboxes / pickers / info thumbs — delegated
  ctx.on(tableDiv, 'change', ev => {
    const t = ev.target;
    if (t.classList.contains('sp-cell-select')) {
      const hook = cfg.after && cfg.after.save;
      save(t.dataset.id, t.dataset.field, t.value).then(() => hook && hook(t.dataset.id, t.dataset.field, t.value));
    } else if (t.classList.contains('sp-row-check')) rowCheck(t);
  });
  ctx.on(tableDiv, 'focusin', async ev => {
    const t = ev.target;
    if (t.classList && t.classList.contains('sp-cell-select') && t.dataset.lazy === '1' && !t.dataset.loaded) {
      const lk = await loadLookup(t.dataset.lookup);
      state._lkc[t.dataset.lookup] = lk;
      const cur = t.dataset.current;
      t.innerHTML = '<option value="0"></option>' + Array.from(lk.map.entries()).map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(l)}</option>`).join('');
      t.dataset.loaded = '1';
    }
  });
  ctx.on(tableDiv, 'click', async ev => {
    const btn = ev.target.closest && ev.target.closest('button[data-picker]');
    if (btn) {
      const c = cfg.cells.find(x => x.id === btn.dataset.field);
      const lk = await loadLookup(btn.dataset.picker); state._lkc[btn.dataset.picker] = lk;
      spOpenMediaPicker(btn, {
        items: lk.items, current: parseInt(btn.dataset.current),
        getId: it => lk.idOf(it), getName: it => shortMediaName(lk.labelOf(it)),
        getThumb: it => spSmallThumb(it[c.thumb || 'thumbnail']), getDur: it => fmtDur(it[c.dur || 'duration']),
        onPick: (id, it) => { save(btn.dataset.id, btn.dataset.field, id); btn.dataset.current = id; spSetPickerBtn(btn, it ? shortMediaName(lk.labelOf(it)) : '— select —', it ? spSmallThumb(it[c.thumb || 'thumbnail']) : null); },
      });
      return;
    }
    const img = ev.target.closest && ev.target.closest('img[data-meta]');
    if (img) { const { showMediaMeta } = await import('./media_meta.js'); showMediaMeta(img.dataset.meta, img.dataset.id); return; }
    if (cfg.onClick) cfg.onClick(ev, { reload, api, ctx, state });
  });

  // lazy placeholder labels (scene names on the link tables) once the lookup lands
  for (const [name, lk] of Object.entries(cfg.lookups || {})) {
    if (!lk.lazy) continue;
    loadLookup(name).then(v => { state._lkc[name] = v; tableDiv.querySelectorAll(`select[data-lookup="${name}"]:not([data-loaded])`).forEach(sel => { const o = sel.options[0]; if (o) o.textContent = v.map.get(String(sel.dataset.current)) || ''; }); tableDiv.querySelectorAll(`button[data-picker="${name}"]`).forEach(b => { const it = v.items.find(x => parseInt(v.idOf(x)) === parseInt(b.dataset.current)); if (it) spSetPickerBtn(b, shortMediaName(v.labelOf(it)), spSmallThumb(it.thumbnail)); }); });
  }

  if (state.filters) wireFilters(outlet, ctx, () => { reload(); });
  if (cfg.extras) await cfg.extras(ctx, { grid, reload, api, outlet, extra: outlet.querySelector('#sp-table-extra'), state });
  ctx.cleanup(() => { if (window.spGrid === grid) window.spGrid = null; });
  return { grid, reload };
}

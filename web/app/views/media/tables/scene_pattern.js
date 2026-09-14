// Scene RPiLED Patterns (templates/scenePattern_table.html).
// Rows: (scenePattern_ID, scene_ID, patternType, params JSON, orderBy). The
// pattern vocabulary comes from /api/led/patterns (led_patterns.py) so the
// per-row editor renders only the fields the chosen pattern honors.
import { SCENE_LOOKUP } from './_common.js';
import { esc } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { hexToRgbArr, rgbArrToHex, rgbCss } from './_color.js';

const primeKey = 'scenePattern_ID';

// ── Pattern registry (served from led_patterns.py) ─────────────────────────
let REG = null;
const REG_MAP = {};
let regPromise = null;
function loadReg() {
  if (!regPromise) {
    regPromise = api.get('/api/led/patterns', { quiet: true }).then(j => {
      REG = j; j.patterns.forEach(p => { REG_MAP[p.type] = p; }); return j;
    }).catch(e => { regPromise = null; throw e; });
  }
  return regPromise;
}
loadReg().catch(() => {});

const ROWS = {};              // scenePattern_ID -> {patternType, params} from the last render
let renderedBlind = false;    // a row rendered before the registry landed

function patternName(type) { return REG_MAP[type] ? REG_MAP[type].name : (type || '?'); }

function summaryHtml(type, params) {
  const spec = REG_MAP[type];
  if (!spec) { renderedBlind = !REG; return '<em>unknown pattern</em>'; }
  const p = params || {};
  const out = [];
  spec.params.forEach(f => {
    const v = p[f.key];
    if (f.kind === 'rgb') out.push(`<span class="sp-led-swatch" title="${esc(f.label)}" style="background:${rgbCss(v)}"></span>`);
    else if (f.kind === 'choice') { const c = (f.choices || []).find(x => String(x[0]) === String(v)); out.push(esc(c ? c[1] : v)); }
    else if (f.key === 'duration') out.push(v > 0 ? esc(v) + 's' : '&infin;');
    else if (f.key === 'brightness') out.push(Math.round((v || 0) * 100) + '%');
    else out.push(esc(f.label.toLowerCase()) + ' ' + esc(v) + (f.unit ? esc(f.unit) : ''));
  });
  return `<span class="sp-led-sum">${out.join('<span class="sep">&middot;</span>')}</span>`;
}

const STYLE = `<style>
  .sp-led-swatch { display:inline-block; width:1.1em; height:1.1em; border-radius:3px; border:1px solid rgba(0,0,0,.35); vertical-align:middle; margin-right:.2em; }
  .sp-led-sum { white-space:nowrap; font-size:.9em; }
  .sp-led-sum .sep { opacity:.45; margin:0 .35em; }
  #ledEditFields .form-label { margin-bottom:.1rem; font-weight:600; }
  #ledEditFields .hint { font-size:.8em; opacity:.7; }
  #ledEditFields .sp-led-universal { border-top:1px solid var(--sp-border, #ccc); margin-top:.75rem; padding-top:.5rem; }
</style>`;

const INTRO = `<p class="text-muted small mb-2">A scene's rows play in <b>Order</b> and repeat until the scene changes.
  Rows that share the same Order play in a random order each pass. A Duration of 0 holds that
  pattern until the next scene (rows after it won't play) — end with a black Solid to go dark on purpose.</p>`;

const MODAL = `<div class="modal fade" id="ledEditModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-scrollable"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Edit LED pattern</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
    <div class="modal-body">
      <div class="mb-2"><label class="form-label fw-bold" for="ledEditType">Pattern</label>
        <select id="ledEditType" class="form-select"></select>
        <div id="ledEditDesc" class="hint text-muted small mt-1"></div></div>
      <div id="ledEditFields"></div>
    </div>
    <div class="modal-footer">
      <span id="ledEditStatus" class="me-auto small text-muted"></span>
      <button type="button" class="btn btn-outline-secondary" id="ledEditTestBtn" title="Push these settings to the lights without saving">Test</button>
      <button type="button" class="btn btn-primary" id="ledEditSaveBtn">Save</button>
    </div>
  </div></div></div>`;

const saveChange = obj => api.post('/api/scenePattern', obj, { quiet: true });
const postTest = body => api.post('/api/RPiLEDTest', body, { quiet: true });

let editor = null;   // { root, edit:{id,type,params}, reload }

function renderFields(root) {
  const spec = REG_MAP[editor.edit.type];
  root.querySelector('#ledEditDesc').textContent = spec.desc || '';
  const box = root.querySelector('#ledEditFields');
  box.innerHTML = '';
  let universalShown = false;
  spec.params.forEach(f => {
    const v = (f.key in editor.edit.params) ? editor.edit.params[f.key] : f.default;
    const wrap = document.createElement('div');
    wrap.className = 'mb-2';
    if (!universalShown && (f.key === 'brightness' || f.key === 'duration')) { wrap.classList.add('sp-led-universal'); universalShown = true; }
    const label = document.createElement('label');
    label.className = 'form-label'; label.textContent = f.label + (f.unit ? ` (${f.unit})` : ''); label.htmlFor = 'ledf_' + f.key;
    wrap.appendChild(label);
    let input;
    if (f.kind === 'rgb') {
      input = document.createElement('input'); input.type = 'color'; input.className = 'form-control form-control-color'; input.value = rgbArrToHex(v);
    } else if (f.kind === 'choice') {
      input = document.createElement('select'); input.className = 'form-select';
      (f.choices || []).forEach(c => { const o = document.createElement('option'); o.value = c[0]; o.textContent = c[1]; if (String(c[0]) === String(v)) o.selected = true; input.appendChild(o); });
    } else {
      input = document.createElement('input'); input.type = 'number'; input.className = 'form-control';
      if (f.min !== undefined) input.min = f.min;
      if (f.max !== undefined) input.max = f.max;
      input.step = f.step !== undefined ? f.step : (f.kind === 'float' ? 0.01 : 1);
      input.value = v;
    }
    input.id = 'ledf_' + f.key; input.dataset.key = f.key; input.dataset.kind = f.kind;
    wrap.appendChild(input);
    if (f.hint) { const hint = document.createElement('div'); hint.className = 'hint'; hint.textContent = f.hint; wrap.appendChild(hint); }
    box.appendChild(wrap);
  });
}

function readFields(root) {
  const out = {};
  root.querySelectorAll('#ledEditFields [data-key]').forEach(el => {
    const k = el.dataset.key;
    out[k] = el.dataset.kind === 'rgb' ? hexToRgbArr(el.value) : Number(el.value);
  });
  return out;
}

function setStatus(msg) { const el = editor && editor.root.querySelector('#ledEditStatus'); if (el) el.textContent = msg || ''; }

function openEditor(id) {
  const r = ROWS[id];
  if (!r || !REG || !editor) return;
  editor.edit = { id, type: r.patternType, params: Object.assign({}, r.params || {}) };
  if (!REG_MAP[editor.edit.type]) { editor.edit.type = REG.patterns[0].type; editor.edit.params = {}; }
  const sel = editor.root.querySelector('#ledEditType');
  sel.innerHTML = '';
  REG.patterns.forEach(p => { const o = document.createElement('option'); o.value = p.type; o.textContent = p.name; if (p.type === editor.edit.type) o.selected = true; sel.appendChild(o); });
  renderFields(editor.root);
  setStatus('');
  window.bootstrap.Modal.getOrCreateInstance(editor.root.querySelector('#ledEditModal')).show();
}

export default {
  id: 'scenePattern', title: 'Scene RPiLED Patterns', primeKey,
  endpoints: { list: '/api/scenePattern', update: '/api/scenePattern', add: '/api/scenepatternaddrow', del: '/api/scenepatterndelrow' },
  filters: { campaign: true, scene: true },
  // New rows start UNASSIGNED (no scene prompt) — pick the scene from the row's
  // dropdown afterwards; unassigned rows always show whatever the filter.
  lookups: { scenes: SCENE_LOOKUP },
  cells: [
    { id: 'scenePattern_ID', hidden: true },
    { id: 'scene_ID', name: 'Scene', cell: 'select', lookup: 'scenes', lazy: true, sort: false },
    { id: 'patternType', name: 'Pattern', cell: 'html', render: (t, row, h) => `<button type="button" class="btn btn-link p-0 text-start" data-led-edit="${esc(h.rowId)}">${esc(patternName(t))}</button>` },
    { id: 'params', name: 'Settings', sort: false, cell: 'html', render: (params, row, h) => { ROWS[h.rowId] = { patternType: h.cellVal('patternType'), params }; return summaryHtml(h.cellVal('patternType'), params); } },
    { id: 'orderBy', name: 'Order', cell: 'text' },
    { id: 'edit', name: '', sort: false, cell: 'html', render: (v, row, h) => `<button type="button" class="btn btn-primary btn-sm" data-led-edit="${esc(h.rowId)}">Edit</button>` },
    { id: 'sendTest', name: 'Test', sort: false, cell: 'html', render: (v, row, h) => `<button type="button" class="btn btn-outline-secondary btn-sm" data-led-test="${esc(h.rowId)}">Test</button>` },
    { cell: 'check' },
  ],
  onClick(ev) {
    const e = ev.target.closest && ev.target.closest('button[data-led-edit]');
    if (e) { openEditor(e.dataset.ledEdit); return; }
    const t = ev.target.closest && ev.target.closest('button[data-led-test]');
    if (t) postTest({ [primeKey]: t.dataset.ledTest }).then(() => toast.success('Sent to the lights.')).catch(x => toast.error('Test failed: ' + x.message));
  },
  async extras(ctx, { reload, outlet, extra }) {
    const scroll = outlet.querySelector('.sp-table-scroll');
    const head = outlet.querySelector('.sp-page-head');
    (head || scroll).insertAdjacentHTML('afterend', STYLE + INTRO);
    extra.innerHTML = MODAL;
    editor = { root: extra, edit: null, reload };
    const modalEl = extra.querySelector('#ledEditModal');
    ctx.on(extra.querySelector('#ledEditType'), 'change', ev => {
      // Switching pattern: keep values for params the new pattern also has
      // (colors, brightness, duration survive), default the rest.
      const current = readFields(extra);
      editor.edit.type = ev.target.value;
      const keep = {};
      REG_MAP[editor.edit.type].params.forEach(f => { if (f.key in current) keep[f.key] = current[f.key]; });
      editor.edit.params = keep;
      renderFields(extra);
    });
    ctx.on(extra.querySelector('#ledEditSaveBtn'), 'click', async () => {
      if (!editor.edit) return;
      setStatus('Saving…');
      try {
        await saveChange({ [primeKey]: editor.edit.id, patternType: editor.edit.type, params: readFields(extra) });
        window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        reload();
      } catch (e) { setStatus('Save failed: ' + e.message); }
    });
    ctx.on(extra.querySelector('#ledEditTestBtn'), 'click', async () => {
      if (!editor.edit) return;
      setStatus('Sending to lights…');
      try {
        await postTest({ [primeKey]: editor.edit.id, patternType: editor.edit.type, params: readFields(extra) });
        setStatus('Sent — lights show these settings until the next scene.');
      } catch (e) { setStatus('Test failed: ' + e.message); }
    });
    ctx.cleanup(() => {
      try { const m = window.bootstrap.Modal.getInstance(modalEl); if (m) m.dispose(); } catch (e) {}
      document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
      document.body.classList.remove('modal-open');
      editor = null;
    });
    try {
      await loadReg();
      if (renderedBlind) { renderedBlind = false; reload(); }
    } catch (e) {
      toast.error('Could not load the LED pattern registry (' + e.message + ').');
    }
  },
};

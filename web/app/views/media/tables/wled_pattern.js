// WLED Pattern Table (templates/wledPattern_table.html).
// Scene -> WLED device rows: effect + palette pick lists (/api/effects,
// /api/pallettes), the WLED-role servers from /api/serverIP, three colours
// stored as "[r,g,b]" text, speed/brightness/order, a Test button.
import { SCENE_LOOKUP, SCENE_ADDROW } from './_common.js';
import { esc } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { rgbTextToHex, hexToRgbText } from './_color.js';

const primeKey = 'wledPattern_ID';

// WLED-role servers only (the old page hard-coded role 4 = WLED; resolve the
// role by name with 4 as the fallback).
let SERVERS = null;
let serversPromise = null;
let renderedBlind = false;
function loadServers() {
  if (!serversPromise) {
    serversPromise = Promise.all([
      api.get('/api/serverrole', { quiet: true }).catch(() => ({ data: [] })),
      api.get('/api/serverIP', { quiet: true }),
    ]).then(([roles, servers]) => {
      const wled = (roles.data || []).find(r => String(r.name || '').trim().toLowerCase() === 'wled');
      const roleId = wled ? wled.ID : 4;
      SERVERS = (servers.data || []).filter(s => parseInt(s.serverroleid, 10) === parseInt(roleId, 10));
      return SERVERS;
    }).catch(e => { serversPromise = null; throw e; });
  }
  return serversPromise;
}
loadServers().catch(() => {});

function serverSelect(cellData, rowId) {
  if (!SERVERS) renderedBlind = true;
  const opts = ['<option value="0"></option>'].concat((SERVERS || []).map(s =>
    `<option value="${esc(s.ServerIP_ID)}"${String(s.ServerIP_ID) === String(cellData) ? ' selected' : ''}>${esc(s.serverName)}</option>`));
  return `<select class="sp-cell-select" data-field="server_ID" data-id="${esc(rowId)}">${opts.join('')}</select>`;
}

const colorCell = field => ({
  id: field, name: field, sort: false, cell: 'html',
  render: (v, row, h) => `<input type="color" class="sp-color-cell" data-field="${field}" data-id="${esc(h.rowId)}" value="${rgbTextToHex(v)}" title="${esc(v || '')}">`,
});

export default {
  id: 'wledPattern', title: 'WLED Pattern Table', primeKey,
  endpoints: { list: '/api/wledPattern', update: '/api/wledPattern', add: '/api/wledpatternaddrow', del: '/api/wledpatterndelrow' },
  filters: { campaign: true, scene: true }, addRow: SCENE_ADDROW,
  lookups: {
    scenes: SCENE_LOOKUP,
    effects: { url: '/api/effects', id: 'ef_ID', label: r => String(r.effectName || '').split('@')[0] },
    pallettes: { url: '/api/pallettes', id: 'pa_ID', label: 'palletteName' },
  },
  cells: [
    { id: 'wledPattern_ID', hidden: true },
    { id: 'scene_ID', name: 'Scenes', cell: 'select', lookup: 'scenes', lazy: true, sort: false },
    { id: 'server_ID', name: 'Server', sort: false, cell: 'html', render: (v, row, h) => serverSelect(v, h.rowId) },
    { id: 'effect', name: 'Effect', cell: 'select', lookup: 'effects', blank: true, sort: false },
    { id: 'pallette', name: 'Pallette', cell: 'select', lookup: 'pallettes', blank: true, sort: false },
    colorCell('color1'),
    colorCell('color2'),
    colorCell('color3'),
    { id: 'speed', name: 'Speed', cell: 'text', sort: false },
    { id: 'brightness', name: 'Brightness', cell: 'text', sort: false },
    { id: 'orderBy', name: 'OrderBy', cell: 'text' },
    { id: 'sendTest', name: 'WLED Test', sort: false, cell: 'html', render: (v, row, h) => `<input type="button" class="btn btn-primary" value="Test" data-wled-test="${esc(h.rowId)}">` },
    { cell: 'check' },
  ],
  onClick(ev, { api }) {
    const b = ev.target.closest && ev.target.closest('input[data-wled-test]');
    if (!b) return;
    api.post('/api/WLEDTest', { [primeKey]: b.dataset.wledTest }, { quiet: true })
      .then(() => toast.success('Sent to the WLED device.'))
      .catch(e => toast.error('Test failed: ' + e.message));
  },
  async extras(ctx, { reload, outlet, api }) {
    const tableDiv = outlet.querySelector('#table');
    // colour pickers: "#rrggbb" -> "[r,g,b]" like site.js clickColor() did
    ctx.on(tableDiv, 'change', ev => {
      const t = ev.target;
      if (!t.classList || !t.classList.contains('sp-color-cell')) return;
      const rgb = hexToRgbText(t.value);
      t.title = rgb;
      api.post('/api/wledPattern', { [primeKey]: t.dataset.id, [t.dataset.field]: rgb }, { quiet: true })
        .catch(e => toast.error('Save failed: ' + e.message));
    });
    try {
      await loadServers();
      if (renderedBlind) { renderedBlind = false; reload(); }
    } catch (e) {
      toast.error('Could not load the server list (' + e.message + ').');
    }
  },
};

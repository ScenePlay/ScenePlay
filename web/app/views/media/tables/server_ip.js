// Server IP Table (templates/serverIP_table.html) + the LAN scan card.
// The scan runs server-side (discovery.py); progress arrives on the `netscan`
// SSE topic, with the old 500 ms poll of /api/pingnetwork/status as the
// fallback while SSE is down.
import { YES_NO } from './_common.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';

const primeKey = 'ServerIP_ID';
let lookupState = null;   // table_editor state (for the role names in after.save)

const CARD = `<div id="pingCard" style="display:flex;align-items:center;gap:10px;margin:6px 0;">
  <input type="button" id="pingNetworkBtn" class="btn btn-primary" value="Ping Network">
  <div id="pingBarWrap" style="display:none;flex:1;max-width:420px;height:10px;background:var(--sp-bg);border:1px solid var(--sp-border);border-radius:5px;overflow:hidden;">
    <div id="pingBar" style="height:100%;width:0%;background:var(--sp-accent);transition:width .3s;"></div>
  </div>
  <span id="pingStatus" style="font-size:.85em;color:var(--sp-muted);"></span>
</div>`;

const RUNNING = ['sweeping', 'identifying'];

export default {
  id: 'serverIP', title: 'Server IP Table', primeKey,
  endpoints: { list: '/api/serverIP', update: '/api/serverIP', add: '/api/serveripaddrow', del: '/api/serveripdelrow' },
  lookups: { roles: { url: '/api/serverrole', id: 'ID', label: 'name' } },
  cells: [
    { id: 'ServerIP_ID', hidden: true },
    { id: 'serverName', name: 'Server Name', cell: 'text' },
    { id: 'version', name: 'Version' },
    { id: 'ipAddress', name: 'IP Address', cell: 'text' },
    { id: 'ports', name: 'Ports', sort: false },
    { id: 'active', name: 'active', cell: 'select', options: YES_NO, sort: false },
    { id: 'PingTime', name: 'PingTime' },
    { id: 'serverroleid', name: 'serverroleid', cell: 'select', lookup: 'roles', blank: true, sort: false },
    { cell: 'check' },
  ],
  after: {
    // Moving a box onto the WLED role: offer to pull its effect/palette tables
    // (the old page hard-coded role 4 = WLED; match by name, 4 as fallback).
    save(id, field, value) {
      if (field !== 'serverroleid') return;
      const roles = lookupState && lookupState._lkc && lookupState._lkc.roles;
      const label = roles ? String(roles.map.get(String(value)) || '') : '';
      const isWled = label ? label.trim().toLowerCase() === 'wled' : String(value) === '4';
      if (!isWled) return;
      if (!confirm('Update the Support tables?')) return;
      api.post('/updateWLEDSupport', { [primeKey]: id }, { quiet: true })
        .then(() => toast.success('WLED support tables updated.'))
        .catch(e => toast.error('Support table update failed: ' + e.message));
    },
  },
  async extras(ctx, { reload, outlet, state }) {
    lookupState = state;
    ctx.cleanup(() => { lookupState = null; });
    const scroll = outlet.querySelector('.sp-table-scroll');
    scroll.insertAdjacentHTML('beforebegin', CARD);
    const btn = outlet.querySelector('#pingNetworkBtn');
    const wrap = outlet.querySelector('#pingBarWrap');
    const bar = outlet.querySelector('#pingBar');
    const label = outlet.querySelector('#pingStatus');
    let active = false;     // a scan we started or found running (ignore stale SSE snapshots)
    let reloadTimer = null;

    const render = p => {
      if (!p || !p.state) return;
      if (RUNNING.includes(p.state)) {
        active = true;
        btn.disabled = true;
        wrap.style.display = '';
        const pct = p.total ? Math.round(100 * p.done / p.total) : 0;
        bar.style.width = pct + '%';
        label.textContent = p.state === 'sweeping'
          ? `scanning ${p.done}/${p.total} host:port probes…`
          : `identifying ${p.done}/${p.total} responders…`;
        return;
      }
      if (!active) return;                  // an old result replayed on connect
      active = false;
      btn.disabled = false;
      if (p.state === 'done' && p.summary) {
        wrap.style.display = '';
        bar.style.width = '100%';
        const s = p.summary;
        label.textContent = `done — ${s.sceneplay} ScenePlay, ${s.wled} WLED, ${s.obs || 0} OBS (${s.created} new, ${s.updated} updated)`;
        // refresh so freshly discovered rows appear in the grid
        if (!reloadTimer) reloadTimer = ctx.after(1500, () => { reloadTimer = null; reload(); });
      } else if (p.state === 'error') {
        label.textContent = 'scan failed — check the server log';
      }
    };

    const fetchStatus = () => api.get('/api/pingnetwork/status', { quiet: true });
    ctx.subscribe('netscan', render, { fallback: { every: 500, fetch: fetchStatus } });

    ctx.on(btn, 'click', async () => {
      btn.disabled = true;
      label.textContent = 'starting…';
      active = true;
      try {
        const r = await api.post('/api/pingnetwork', null, { quiet: true });
        if (r && r.started === false) label.textContent = 'a scan is already running…';
        // SSE carries the progress; one direct read covers a slow topic (re)subscribe
        ctx.after(600, () => fetchStatus().then(render).catch(() => {}));
      } catch (e) {
        active = false;
        btn.disabled = false;
        label.textContent = 'could not start scan';
      }
    });

    // A scan may already be running (started elsewhere / page reopened
    // mid-scan) — pick its progress bar back up.
    fetchStatus().then(p => { if (p && RUNNING.includes(p.state)) render(p); }).catch(() => {});
  },
};

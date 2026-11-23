// Utilities → Network & Hotspot card: status, fallback / play-mode switches,
// saved networks, join a network. API: routers/network.py (the root daemon
// ops/netwatch.py does the actual switching).
import { html, render, esc } from '../../../lib/dom.js';
import { api, ApiError } from '../../../api.js';
import { toast } from '../../../ui/toast.js';

const OTHER = '\u0000other';
const MODE_TEXT = {
  client: 'Online', starting: 'Starting up — waiting for a known network', waiting: 'Lost the network — hotspot soon',
  offline: 'Offline (fallback hotspot is off)', hotspot: 'Fallback hotspot is up', play: 'Hotspot play mode',
  connecting: 'Connecting…', no_wifi: 'No Wi-Fi adapter', unavailable: 'Not available',
};
const muted = 'font-size:.85em;color:var(--sp-muted);';

function statusLine(s) {
  if (!s.available) return html`<p style="margin:6px 0;"><b>Not available.</b> <span style="${muted}">${s.reason || ''}</span></p>`;
  const where = s.mode === 'client'
    ? (s.wifi ? html` on Wi-Fi <b>${s.wifi_ssid || s.wifi}</b>` : s.ethernet ? html` on Ethernet` : '') : '';
  const addr = s.ip ? html` &middot; <code>${s.ip}</code>` : '';
  const host = s.hostname ? html` &middot; <code>http://${s.hostname}.local</code>` : '';
  const la = s.last_attempt;
  const last = la && la.ok === false && la.error ? html`<div class="alert alert-danger py-1 px-2 my-1" style="font-size:.85em;">Could not join <b>${la.ssid}</b>: ${la.error}</div>`
    : la && la.ok === true ? html`<div style="${muted}">Last join: <b>${la.ssid}</b> worked (${la.at}).</div>` : '';
  return html`<p style="margin:6px 0;"><b>${MODE_TEXT[s.mode] || s.mode}</b>${where}${addr}${host}</p>
    <p style="${muted}margin:2px 0;">Hotspot name: <b>${s.hotspot_ssid || '—'}</b> (${s.hotspot_open ? 'open' : 'password protected'})</p>${last}`;
}

export async function mountNetwork(el, ctx, isDm) {
  let st = await api.get('/api/v1/network/status', { quiet: true }).catch(() => ({ available: false, reason: 'ScenePlay did not answer.' }));
  if (!isDm || !st.available) {
    render(el, html`<div id="net-status">${statusLine(st)}</div>
      ${st.available && !isDm ? html`<p style="margin:6px 0;"><a href="/login?next=/utilities">Log in with a DM account</a> to change network settings.</p>` : ''}
      <p style="${muted}">When this box cannot reach any network it opens an open Wi-Fi hotspot so a phone can set it up. Linux / Raspberry Pi only.</p>`);
    return;
  }
  const [set, saved] = await Promise.all([
    api.get('/api/v1/network/settings', { quiet: true }).catch(() => ({ fallback_enabled: true, play_mode: false })),
    api.get('/api/v1/network/saved', { quiet: true }).catch(() => ({ saved: [] })),
  ]);
  const ro = st.writes_allowed ? '' : 'disabled';
  render(el, html`
    <div id="net-status">${statusLine(st)}</div>
    ${st.writes_allowed ? '' : html`<p class="alert alert-warning py-1 px-2" style="font-size:.85em;">Network control is off on this instance (dev / test server).</p>`}
    <label style="display:block;margin:8px 0 2px;"><input type="checkbox" id="net-fallback" ${set.fallback_enabled ? 'checked' : ''} ${ro}> <b>Fallback hotspot</b> — if no known network connects (about a minute after boot, or after losing Wi-Fi), open the hotspot so a phone can pick a network.</label>
    <ul style="${muted}margin:2px 0 6px 18px;"><li>The fallback hotspot is <b>open</b> (no password) so a brand-new box can be set up. While it is up, anyone in range can reach the setup page and ScenePlay.</li><li>Every 5 minutes with no phone connected, it steps down to look for a saved network again.</li><li>Your phone's "sign in to network" popup opens the setup page. If it doesn't, browse to <code>http://10.42.0.1/setup/wifi</code>.</li></ul>
    <label style="display:block;margin:8px 0 2px;"><input type="checkbox" id="net-play" ${set.play_mode ? 'checked' : ''} ${ro}> <b>Hotspot play mode</b> — keep the hotspot up on purpose so players' phones join ScenePlay directly (somewhere without Wi-Fi). No internet, no remote relay while it is on.</label>
    <div class="d-flex gap-2 align-items-center flex-wrap" style="margin:4px 0 4px 22px;">
      <input type="password" id="net-play-pw" class="form-control form-control-sm" style="max-width:220px;" autocomplete="new-password" placeholder="${set.has_play_password ? 'password set — type to change' : 'optional password (8–63)'}" ${ro}>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="net-play-pw-save" ${ro}>Save password</button>
      ${set.has_play_password ? html`<button type="button" class="btn btn-sm btn-outline-danger" id="net-play-pw-clear" ${ro}>Make it open</button>` : ''}
    </div>
    <p style="${muted}margin:0 0 8px 22px;">Turning play mode on drops this box off your Wi-Fi: reconnect your device to <b>${st.hotspot_ssid || 'the hotspot'}</b> and open <code>http://10.42.0.1</code>.</p>
    <hr style="margin:8px 0;">
    <b style="font-size:.9em;">Saved networks</b>
    ${saved.saved.length ? html`<table style="margin:4px 0 8px;font-size:.9em;">${saved.saved.map(n => html`<tr>
        <td style="border:none;padding-right:12px;">${n.ssid}${n.name !== n.ssid ? html` <span style="${muted}">(${n.name})</span>` : ''}${st.wifi === n.name ? html` <b style="color:var(--sp-ok, #3c9a5f);">· connected</b>` : ''}</td>
        <td style="border:none;"><button type="button" class="btn btn-outline-danger btn-sm" data-net-forget="${n.name}" ${ro}>Forget</button></td></tr>`)}</table>`
      : html`<p style="${muted}margin:4px 0 8px;">None yet.</p>`}
    <b style="font-size:.9em;">Join a network</b>
    <div class="d-flex gap-2 align-items-center flex-wrap" style="margin:4px 0;">
      <select id="net-pick" class="form-select form-select-sm" style="max-width:280px;" ${ro}><option value="">Press Scan to list networks…</option><option value="${OTHER}">Other / hidden network…</option></select>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="net-scan" ${ro}>Scan</button></div>
    <input type="text" id="net-ssid" class="form-control form-control-sm mb-1" style="max-width:280px;display:none;" placeholder="Network name" autocomplete="off" ${ro}>
    <input type="password" id="net-pw" class="form-control form-control-sm mb-1" style="max-width:280px;" placeholder="Wi-Fi password (blank for open)" autocomplete="new-password" ${ro}>
    <button type="button" class="btn btn-sm btn-primary" id="net-join" ${ro}>Connect</button>
    <p style="${muted}margin:4px 0;">If you are using ScenePlay over Wi-Fi, this page loses the connection while the box switches. If the new network fails, the box goes back to a saved network, or opens the hotspot.</p>`);

  const $ = s => el.querySelector(s);
  const save = async body => {
    try { await api.post('/api/v1/network/settings', body); toast.success('Saved'); return true; } catch (e) { return false; }
  };
  ctx.on($('#net-fallback'), 'change', e => save({ fallback_enabled: e.target.checked }));
  ctx.on($('#net-play'), 'change', async e => {
    if (e.target.checked && !confirm(`Turn on hotspot play mode? This box leaves your Wi-Fi and becomes the "${st.hotspot_ssid}" hotspot.`)) { e.target.checked = false; return; }
    if (!(await save({ play_mode: e.target.checked }))) e.target.checked = !e.target.checked;
  });
  ctx.on($('#net-play-pw-save'), 'click', async () => {
    const pw = $('#net-play-pw').value;
    if (!pw) { toast.warn('Type a password first (or use "Make it open").'); return; }
    if (await save({ play_password: pw })) ctx.reload();
  });
  const clr = $('#net-play-pw-clear');
  if (clr) ctx.on(clr, 'click', async () => { if (await save({ play_password: '' })) ctx.reload(); });

  ctx.on(el, 'click', async e => {
    const b = e.target.closest('[data-net-forget]');
    if (!b) return;
    const name = b.dataset.netForget;
    const live = st.wifi === name ? ' This is the network the box is on right now — it will disconnect.' : '';
    if (!confirm(`Forget "${name}"? The box will no longer join it by itself.${live}`)) return;
    try { await api.post('/api/v1/network/forget', { name }); b.closest('tr').remove(); toast.success('Forgotten'); } catch (x) { /* toasted */ }
  });

  const pick = $('#net-pick');
  const onPick = () => { $('#net-ssid').style.display = pick.value === OTHER ? '' : 'none'; };
  ctx.on(pick, 'change', onPick);
  ctx.on($('#net-scan'), 'click', async () => {
    const btn = $('#net-scan'); btn.disabled = true; btn.textContent = 'Scanning…';
    try {
      const r = await api.get('/api/v1/network/scan');
      pick.innerHTML = r.networks.map(n => `<option value="${esc(n.ssid)}" data-security="${esc(n.security)}">${esc(n.ssid)} — ${n.signal}%${n.security ? ' 🔒' : ''}</option>`).join('')
        + `<option value="${OTHER}">Other / hidden network…</option>`;
      onPick();
    } catch (x) { /* toasted */ } finally { btn.disabled = false; btn.textContent = 'Scan'; }
  });
  ctx.on($('#net-join'), 'click', async () => {
    const other = pick.value === OTHER;
    const ssid = other ? $('#net-ssid').value.trim() : pick.value;
    if (!ssid) { toast.warn('Pick a network (Scan) or choose "Other".'); return; }
    if (!confirm(`Switch this box to "${ssid}"? If you are on Wi-Fi, this page will lose the connection for a moment.`)) return;
    const opt = pick.selectedOptions[0];
    try {
      await api.post('/api/v1/network/connect', { ssid, password: $('#net-pw').value, hidden: other, security: other ? '' : (opt && opt.dataset.security) || '' });
      $('#net-pw').value = '';
      toast.success(`Connecting to ${ssid}…`);
    } catch (x) { if (!(x instanceof ApiError)) throw x; }
  });

  ctx.every(5000, async () => {
    if (!el.isConnected || !el.closest('details')?.open) return;
    try { st = await api.get('/api/v1/network/status', { quiet: true }); render($('#net-status'), statusLine(st)); } catch (e) { /* box switching networks */ }
  });
}

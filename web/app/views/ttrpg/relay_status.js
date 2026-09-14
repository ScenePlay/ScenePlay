// Relay admin (templates/ttrpg/relay_status.html): status, join code,
// players online, connection settings (auto-save), party sync.
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { toast } from '../../ui/toast.js';
import { spPickOption } from '../../ui/pick_option.js';

export const title = 'Relay Admin';

const ON  = '<span class="badge bg-success" style="font-size:.65rem;">&#9679; Online</span>';
const OFF = '<span class="badge bg-secondary" style="font-size:.65rem;">&#9675; Offline</span>';
const hpColor = pct => pct > 50 ? '#28a745' : pct > 25 ? '#ffc107' : '#dc3545';

function syncBadge(age) {
  if (age === null || age === undefined) return '';
  if (age < 15) return html`<span class="badge bg-success ms-1">${age}s ago</span>`;
  if (age < 90) return html`<span class="badge bg-warning text-dark ms-1">${age}s ago</span>`;
  return html`<span class="badge bg-danger ms-1">stalled &mdash; ${Math.floor(age / 60)}m ago</span>`;
}

const BITRATES = [['128', '128 kbps — full quality'], ['96', "96 kbps — saves listeners' mobile data"], ['64', '64 kbps — minimum data']];
const PROFILES = [['low', 'Low lag — ~4-5 s behind live'], ['smooth', 'Smooth — ~10-12 s buffer for shaky networks']];
const GAINS = [['25', '25% — quiet'], ['50', '50% — recommended'], ['75', '75%'], ['100', '100% — source level'], ['150', '150% — boost quiet sources']];
const opts = (list, cur) => list.map(([v, l]) => html`<option value="${v}" ${cur === v ? 'selected' : ''}>${l}</option>`);

function playerRow(p) {
  return html`<tr data-player="${p.player_name}" data-username="${p.username}" data-display="${p.display_name || ''}" style="${p.online ? '' : 'opacity:.55;'}">
    <td class="presence-cell">${raw(p.online ? ON : OFF)}</td>
    <td>${p.username}</td>
    <td class="fw-bold" style="color:var(--ttrpg-accent);">${p.player_name}</td>
    ${p.no_character ? html`<td class="small text-muted fst-italic" colspan="2">Logged in — no character assigned yet</td>`
    : html`<td class="small">${p.char_class} Lv${p.level}</td>
      <td><div class="d-flex align-items-center gap-1">
        <div style="width:60px;background:var(--sp-surface);border-radius:3px;height:8px;overflow:hidden;"><div style="width:${p.hp_pct}%;height:8px;background:${hpColor(p.hp_pct)};"></div></div>
        <span class="small">${p.hp_current}/${p.hp_max}</span></div></td>`}
    <td class="small text-muted">${p.joined_at}</td></tr>`;
}

function page(d) {
  const cfg = d.cfg, on = cfg.enabled === '1';
  const onlineCount = d.logged_in.filter(p => p.online).length;
  return html`<div class="row justify-content-center"><div class="col-lg-7">
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 style="color:var(--ttrpg-accent);" class="mb-0">&#127760; Remote Relay</h4>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="relay-refresh">&#8635; Refresh</button></div>
    ${cfg.boot_tripped ? html`<div class="alert mb-3" style="background:var(--ttrpg-primary);border:1px solid #c0392b;color:#e09090;">
      &#9888; The relay was <strong>automatically disabled</strong> on ${cfg.boot_tripped}: the previous app start crashed while connecting to the relay
      (this can happen on low-memory boxes like a Pi Zero). Enable it again below when you're ready — re-enabling clears this notice.</div>` : ''}

    <div class="ttrpg-card p-3 mb-3"><div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
      <div><span class="fw-bold">Status:</span>
        ${on ? raw('<span class="badge bg-success ms-1">Enabled</span>') : raw('<span class="badge bg-secondary ms-1">Disabled</span>')}
        <span class="small text-muted ms-3">Last sync: <span id="relay-last-sync">${cfg.last_sync}</span> <span id="relay-sync-badge">${syncBadge(d.sync_age)}</span></span></div>
      <form data-api="/ttrpg/relay/toggle" id="relayToggleForm" data-enabling="${on ? '0' : '1'}" data-code="${cfg.code || ''}">
        <input type="hidden" name="session_mode" id="relaySessionMode" value="">
        <button class="btn btn-sm ${on ? 'btn-outline-danger' : 'btn-ttrpg'}">${on ? 'Disable Relay' : 'Enable Relay'}</button></form></div></div>

    <div class="ttrpg-card p-3 mb-3">
      <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div><span class="fw-bold">Join Code:</span>
          ${cfg.code ? html`<span class="ms-2 fw-bold" id="relay-join-code" style="font-size:1.6rem;color:var(--ttrpg-accent);letter-spacing:.2em;">${cfg.code}</span>`
          : html`<span class="text-muted ms-2">No active session</span>`}</div>
        <div class="d-flex gap-2">
          ${cfg.code ? html`<form data-api="/ttrpg/relay/reuse-code"><button class="btn btn-sm btn-ttrpg" title="Reconnect using the same join code — players don't need a new one">&#8634; Reuse Code</button></form>` : ''}
          <form data-api="/ttrpg/relay/generate-code"><button class="btn btn-sm btn-outline-secondary">&#8635; New Session</button></form></div></div>
      ${cfg.code ? html`<div class="small text-muted mt-1">Session ID: ${cfg.session_id}</div>
        <div class="small text-muted">Players log in at the relay portal with their ScenePlay username, password, and this code.
          <strong>&#8634; Reuse Code</strong> reconnects mid-campaign with the code everyone already has;
          <strong>&#8635; New Session</strong> clears all relay data, pushes fresh characters, and mints a new code you'll need to re-send.</div>` : ''}</div>

    ${on && cfg.session_id ? html`<div class="ttrpg-card p-3 mb-3">
      <h6 style="color:var(--ttrpg-accent);" class="mb-3">&#128100; Players Online
        <span id="online-count-badge" class="badge ${onlineCount ? 'bg-success' : 'bg-secondary'} ms-2">${onlineCount} / ${d.logged_in.length}</span></h6>
      ${!d.logged_in.length ? html`<div class="small text-muted">No players have logged in yet. Share the join code above.</div>`
      : html`<div class="table-responsive"><table class="table table-sm mb-0" style="color:var(--sp-text);">
        <thead><tr><th class="small text-muted fw-normal">Status</th><th class="small text-muted fw-normal">Username</th><th class="small text-muted fw-normal">Character</th>
          <th class="small text-muted fw-normal">Class / Lv</th><th class="small text-muted fw-normal">HP</th><th class="small text-muted fw-normal">Joined</th></tr></thead>
        <tbody>${d.logged_in.map(playerRow)}</tbody></table></div>`}</div>` : ''}

    <div class="ttrpg-card p-3 mb-3">
      <h6 style="color:var(--ttrpg-accent);" class="mb-3">Connection Settings</h6>
      <form id="relay-cfg-form">
        <div class="mb-2"><label class="form-label small">Relay URL</label>
          <input type="url" name="relay_url" class="form-control form-control-sm" placeholder="https://your-relay.onrender.com" value="${cfg.url}"></div>
        <div class="mb-2"><label class="form-label small">Shared Secret</label>
          <input type="password" name="relay_secret" class="form-control form-control-sm" placeholder="${cfg.secret_set ? 'leave blank to keep existing' : 'not set'}" value="" autocomplete="new-password"></div>
        <div class="form-check mb-3">
          <input class="form-check-input" type="checkbox" id="relay-audio-enabled" name="relay_audio_enabled" value="1" ${cfg.audio_enabled === '1' ? 'checked' : ''}>
          <label class="form-check-label small" for="relay-audio-enabled">Stream music to portal players
            <span class="text-muted">(live audio of the music player; players use the &#128266; control in the portal to listen)</span></label></div>
        <div class="mb-3 ms-4" style="max-width:280px;"><label class="form-label small">Stream quality</label>
          <select name="relay_audio_bitrate" class="form-select form-select-sm">${opts(BITRATES, cfg.audio_bitrate)}</select>
          <div class="form-text">Applies from the next track or stream restart.</div></div>
        <div class="mb-3 ms-4" style="max-width:280px;"><label class="form-label small">Stream latency</label>
          <select name="relay_audio_profile" class="form-select form-select-sm">${opts(PROFILES, cfg.audio_profile)}</select>
          <div class="form-text">Low lag keeps players near-live; pick Smooth if listeners hear dropouts.</div></div>
        <div class="mb-3 ms-4" style="max-width:280px;"><label class="form-label small">Stream volume</label>
          <select name="relay_audio_gain" class="form-select form-select-sm">${opts(GAINS, cfg.audio_gain)}</select>
          <div class="form-text">Loudness of the music sent to portal players — independent of your local speakers. Applies from the next track.</div></div>
        <span class="small text-muted">&#10003; Settings save automatically as you change them.
          <span id="relay-saved-pill" class="badge bg-success" style="display:none;">&#10003; Saved</span></span></form></div>

    ${on && cfg.session_id ? html`<div class="ttrpg-card p-3 mb-3"><div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
      <div><span class="fw-bold">Party Sync</span><div class="small text-muted">Re-push all session characters without resetting the session.</div></div>
      <form data-api="/ttrpg/relay/sync-characters"><button class="btn btn-sm btn-outline-secondary">&#8679; Sync Characters</button></form></div></div>` : ''}

    <div class="d-flex gap-2 flex-wrap">
      <a href="/ttrpg" class="btn btn-sm btn-outline-secondary">&larr; Dashboard</a>
      <a href="/ttrpg/relay/party" class="btn btn-sm btn-outline-secondary">&#128101; Party View</a>
      <a href="/ttrpg/relay/rolls" class="btn btn-sm btn-outline-secondary">&#127922; Roll Log</a></div>
  </div></div>`;
}

export async function mount(outlet, ctx) {
  const fetchedAt = Date.now() / 1000;
  const d = await api.get('/api/v1/relay/page');
  document.title = 'Relay Admin — ScenePlay';
  render(outlet, page(d));

  ctx.on(outlet.querySelector('#relay-refresh'), 'click', () => ctx.reload());

  // Old form+redirect endpoints: submit as JSON, toast the flash, re-render.
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    // Enabling the relay: ask which session to engage — keep the join code
    // the players already have, or mint a new one. Dropdown modal, never a
    // typed number (spPickOption). No previous code → new session, no ask.
    if (f.id === 'relayToggleForm' && f.dataset.enabling === '1') {
      const mode = f.querySelector('#relaySessionMode');
      if (!mode.value) {
        const code = f.dataset.code;
        if (!code) mode.value = 'new';
        else {
          const pick = await spPickOption('Engage relay',
            'Players log in with a join code. Keep the one they already have, or start fresh?',
            'Session code',
            [{ value: 'reuse', label: `Use existing code ${code}` },
             { value: 'new', label: 'Generate a new code' }],
            'Enable');
          if (!pick) return;                          // cancelled: relay stays off
          mode.value = pick;
        }
      }
    }
    const btn = f.querySelector('button[type=submit], button:not([type])'); if (btn) btn.disabled = true;
    try {
      const r = await api.post(f.dataset.api, Object.fromEntries(new FormData(f).entries()));
      if (r && r.message) (r.ok === false ? toast.warn : toast.success)(r.message, { ms: 8000 });
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });

  // ── auto-save: the same treatment as the OBS Broadcast form ──────────────
  // Every field in Connection Settings saves itself on change. 'change', not
  // 'input': text fields commit on blur, so typing the relay URL doesn't fire
  // a reconnect per keystroke. Debounced + serialised the same way.
  const form = outlet.querySelector('#relay-cfg-form');
  let timer = null, saving = false, again = false;
  function save() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (saving) { again = true; return; }
      saving = true;
      try {
        await api.post('/ttrpg/relay/save-config', Object.fromEntries(new FormData(form).entries()), { quiet: true });
        const pill = outlet.querySelector('#relay-saved-pill');
        if (pill) { pill.style.display = ''; clearTimeout(pill._t); pill._t = setTimeout(() => { pill.style.display = 'none'; }, 2000); }
      } catch (e) {
        toast.error('A relay setting failed to save — check the connection and change it again.');
      } finally {
        saving = false;
        if (again) { again = false; save(); }
      }
    }, 400);
  }
  ctx.on(form, 'change', e => { if (e.target && e.target.name) save(); });
  ctx.cleanup(() => clearTimeout(timer));

  // Live presence: flip the Online/Offline badges without a page refresh.
  // The `relay` SSE topic carries {enabled, ok, problems, sync_age, online};
  // when the stream is down, poll the local server (which relays to the
  // portal's presence endpoint) every 10 s like the old page did.
  const applyPresence = d => {
    if (!d || !d.enabled) return;
    if (d.ts && d.ts < fetchedAt) return;             // SSE hello replaying a snapshot older than this render
    if ('sync_age' in d) { const b = outlet.querySelector('#relay-sync-badge'); if (b) render(b, syncBadge(d.sync_age)); }
    if (d.last_sync) { const s = outlet.querySelector('#relay-last-sync'); if (s) s.textContent = d.last_sync; }
    if (!d.online) return;
    const rows = outlet.querySelectorAll('tr[data-player]');
    if (!rows.length) return;
    let online = 0;
    rows.forEach(tr => {
      // Presence may be keyed by character name, username or the login's
      // display name depending on the relay version — accept any.
      const on = !!(d.online[tr.dataset.player] || d.online[tr.dataset.username] || d.online[tr.dataset.display]);
      if (on) online++;
      tr.style.opacity = on ? '' : '.55';
      const cell = tr.querySelector('.presence-cell');
      if (cell) cell.innerHTML = on ? ON : OFF;
    });
    const badge = outlet.querySelector('#online-count-badge');
    if (badge) { badge.textContent = online + ' / ' + rows.length; badge.className = 'badge ms-2 ' + (online ? 'bg-success' : 'bg-secondary'); }
  };
  ctx.subscribe('relay', applyPresence, { fallback: { every: 10000, fetch: () => api.get('/ttrpg/relay/api/presence', { quiet: true }) } });
}

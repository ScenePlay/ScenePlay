// DM Dashboard (templates/ttrpg/dashboard.html).
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { hpBar, avatar, statusBadge, wrapIds } from './_common.js';

export const title = 'DM Dashboard';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/ttrpg/dashboard');
  if (d.redirect) return ctx.navigate(d.redirect, { replace: true });
  render(outlet, html`
  <div class="sp-page-head"><h2 style="color: var(--ttrpg-accent);">&#9876; DM Dashboard</h2>
    <div><a href="/ttrpg/sessions/new" class="btn btn-ttrpg btn-sm me-2">+ New Session</a><a href="/ttrpg/character/new" class="btn btn-outline-secondary btn-sm">+ New Character</a></div></div>
  ${d.active_session ? html`<div class="alert mb-4" style="background: var(--ttrpg-primary); border: 1px solid var(--ttrpg-accent); color: var(--ttrpg-accent);"><strong>&#9654; Active Session:</strong> ${d.active_session.title} &mdash; Session #${d.active_session.session_number} <a href="/ttrpg/sessions/${d.active_session.session_id}" class="btn btn-ttrpg btn-sm ms-3">Manage</a></div>` : ''}
  <div class="row g-4">
    <div class="col-md-4"><div class="ttrpg-card p-3 h-100"><h5 style="color: var(--ttrpg-accent);">Campaigns</h5>
      ${d.campaigns.length ? html`<div class="sp-table-scroll"><table class="table table-sm table-hover mb-0 ttrpg-table" id="campaignTable"><thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>
        ${d.campaigns.map(c => html`<tr class="campaign-row" data-campaign-id="${c.campaign_id}" data-char-ids="${wrapIds(c.char_ids)}" style="cursor:pointer;" title="Click to see this campaign's sessions and characters"><td>${c.campaign_name}</td><td>${c.active ? raw('<span class="badge bg-success">Active</span>') : raw('<span class="badge bg-secondary">Inactive</span>')}</td></tr>`)}</tbody></table></div>`
        : html`<p class="text-muted small">No campaigns yet. Create one in the main ScenePlay tables.</p>`}</div></div>
    <div class="col-md-8"><div class="ttrpg-card p-3 h-100">
      <div class="d-flex justify-content-between align-items-center mb-2"><h5 style="color: var(--ttrpg-accent);">All Characters</h5><a href="/ttrpg/characters" class="btn btn-sm btn-outline-secondary">Manage</a></div>
      ${d.characters.length ? html`<div class="row g-2">${d.characters.map(c => html`<div class="col-sm-6 col-lg-4">
        <div class="ttrpg-card p-2 d-flex align-items-center gap-2 char-card" data-character-id="${c.character_id}" style="border-color: var(--sp-border); cursor:pointer;" title="Click to show this character's sessions">
          ${avatar(c, 40)}
          <div style="min-width:0;"><a href="/ttrpg/character/${c.character_id}" class="fw-bold text-truncate d-block text-decoration-none" style="color:var(--ttrpg-accent);" title="Open character sheet" data-stop>${c.name}</a>
            <div class="small text-muted text-truncate">Lv${c.level} ${c.char_class || '—'} &bull; ${c.user_display_name}</div>
            ${hpBar(c)}<div class="small text-muted">HP ${c.hp_current}/${c.hp_max}</div></div></div></div>`)}</div>`
        : html`<p class="text-muted small">No characters yet. Players can create their own at <a href="/ttrpg/character/new" style="color:var(--ttrpg-accent);">/ttrpg/character/new</a>.</p>`}</div></div>
    <div class="col-12"><div class="ttrpg-card p-3">
      <div class="d-flex justify-content-between align-items-center mb-2"><div class="d-flex align-items-center gap-2"><h5 style="color: var(--ttrpg-accent);" class="mb-0">Sessions</h5>
        <span id="campaignFilterLabel" style="display:none;font-size:.78rem;padding:2px 10px;border-radius:12px;background:color-mix(in srgb, var(--sp-accent) 20%, transparent);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-accent);"></span></div>
        <a href="/ttrpg/sessions" class="btn btn-sm btn-outline-secondary">All Sessions</a></div>
      ${d.sessions.length ? html`<div class="sp-table-scroll"><table class="table table-sm table-hover mb-0 ttrpg-table" id="sessionsTable"><thead><tr><th>#</th><th>Title</th><th>Campaign</th><th>Date</th><th>Status</th><th></th></tr></thead><tbody>
        ${d.sessions.map(s => html`<tr class="session-row" data-campaign-id="${s.campaign_id ?? ''}" data-char-ids="${wrapIds(s.party_ids)}" data-session-title="#${s.session_number} ${s.title}" style="cursor:pointer;" title="Click to see this session's characters">
          <td>${s.session_number}</td><td>${s.title}</td><td>${s.campaign_name || '—'}</td><td>${s.session_date || '—'}</td><td>${statusBadge(s.status)}</td>
          <td><a href="/ttrpg/sessions/${s.session_id}" class="btn btn-sm btn-outline-secondary" data-stop>Open</a></td></tr>`)}</tbody></table></div>`
        : html`<p class="text-muted small">No sessions yet. <a href="/ttrpg/sessions/new" style="color:var(--ttrpg-accent);">Create the first one.</a></p>`}</div></div>
  </div>`);

  // ONE selection at a time — campaign / session / character filters.
  let activeKind = null, activeId = null;
  const highlight = (el, on) => { el.style.background = on ? 'color-mix(in srgb, var(--sp-accent) 18%, transparent)' : ''; el.style.outline = on ? '1px solid var(--ttrpg-accent)' : ''; };
  const dimChars = matchIds => outlet.querySelectorAll('.char-card').forEach(c => { c.style.opacity = (!matchIds || matchIds.includes(',' + c.dataset.characterId + ',')) ? '' : '0.3'; });
  const lbl = outlet.querySelector('#campaignFilterLabel');
  const clearFilter = () => { activeKind = activeId = null; outlet.querySelectorAll('.campaign-row, .session-row, .char-card').forEach(el => highlight(el, false)); outlet.querySelectorAll('.session-row').forEach(sr => { sr.style.display = ''; }); dimChars(null); lbl.style.display = 'none'; lbl.onclick = null; };
  const select = (kind, id, name, el, sessionMatchFn, charIds) => {
    if (activeKind === kind && activeId === id) { clearFilter(); return; }
    clearFilter(); activeKind = kind; activeId = id; highlight(el, true);
    if (sessionMatchFn) outlet.querySelectorAll('.session-row').forEach(sr => { sr.style.display = sessionMatchFn(sr) ? '' : 'none'; });
    dimChars(charIds || null);
    lbl.textContent = name + '  ×'; lbl.style.display = ''; lbl.style.cursor = 'pointer'; lbl.title = 'Click to clear filter'; lbl.onclick = clearFilter;
  };
  ctx.on(outlet, 'click', e => {
    if (e.target.closest('[data-stop]')) return;
    const cr = e.target.closest('.campaign-row'), sr = e.target.closest('.session-row'), cc = e.target.closest('.char-card');
    if (cr) { const cid = cr.dataset.campaignId; select('campaign', cid, cr.querySelector('td').textContent.trim(), cr, s => s.dataset.campaignId === cid, cr.dataset.charIds); }
    else if (sr) select('session', sr.dataset.sessionTitle, sr.dataset.sessionTitle, sr, null, sr.dataset.charIds);
    else if (cc) { const chid = cc.dataset.characterId; select('character', chid, cc.querySelector('a').textContent.trim(), cc, s => (s.dataset.charIds || '').includes(',' + chid + ','), null); }
  });
}

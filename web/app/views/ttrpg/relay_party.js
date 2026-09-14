// Remote party view (templates/ttrpg/relay_party.html): one card per player
// who has logged into the relay session.
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';

export const title = 'Party View';

const hpColor = pct => pct > 50 ? '#28a745' : pct > 25 ? '#ffc107' : '#dc3545';

function card(c) {
  const s = c.sheet || {};
  return html`<div class="col-md-6 col-xl-4"><div class="ttrpg-card p-3 h-100">
    <div class="d-flex align-items-center gap-2 mb-2">
      <div style="width:42px;height:42px;border-radius:50%;flex-shrink:0;background:var(--ttrpg-primary);border:2px solid var(--ttrpg-accent);display:flex;align-items:center;justify-content:center;font-size:1.1rem;color:var(--ttrpg-accent);">&#9919;</div>
      <div class="flex-grow-1 overflow-hidden">
        <div class="fw-bold text-truncate" style="color:var(--ttrpg-accent);">${s.name || c.player_name}</div>
        <div class="small text-muted">${s.class || '—'} ${s.level ? html`Lv${s.level}` : ''} ${s.race ? html`&middot; ${s.race}` : ''}</div></div></div>
    <div class="d-flex align-items-center gap-2 mb-2">
      <span class="small text-muted" style="min-width:24px;">HP</span>
      <div class="flex-grow-1" style="background:var(--sp-surface);border-radius:4px;height:14px;overflow:hidden;"><div style="width:${c.hp_pct}%;background:${hpColor(c.hp_pct)};height:14px;"></div></div>
      <span class="small fw-bold" style="min-width:52px;text-align:right;">${c.hp_current}/${c.hp_max}</span></div>
    ${s.ac || s.speed || s.passive_perception ? html`<div class="small d-flex gap-3">
      ${s.ac ? html`<span><span class="text-muted">AC</span> <strong>${s.ac}</strong></span>` : ''}
      ${s.speed ? html`<span><span class="text-muted">Spd</span> <strong>${s.speed}</strong></span>` : ''}
      ${s.passive_perception ? html`<span><span class="text-muted">PP</span> <strong>${s.passive_perception}</strong></span>` : ''}</div>` : ''}
    <div class="small text-muted mt-2">Joined ${c.joined_at || c.updated_at}</div></div></div>`;
}

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/relay/party');
  document.title = 'Party View — ScenePlay';
  render(outlet, html`<div class="row justify-content-center"><div class="col-lg-9">
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 style="color:var(--ttrpg-accent);" class="mb-0">&#128101; Remote Party</h4>
      <div class="d-flex gap-2">
        <button type="button" class="btn btn-sm btn-outline-secondary" id="party-refresh">&#8635; Refresh</button>
        <a href="/ttrpg/relay" class="btn btn-sm btn-outline-secondary">&larr; Relay Admin</a></div></div>
    ${d.error ? html`<div class="alert alert-warning py-2">Could not reach relay: ${d.error}</div>` : ''}
    ${!d.cfg.session_id ? html`<div class="ttrpg-card p-3 text-muted">No active relay session. Generate a join code first.</div>`
    : !d.party.length ? html`<div class="ttrpg-card p-3 text-muted">No players have logged into the relay session yet. Characters are pre-registered — they will appear here once each player signs in.</div>`
    : html`<div class="row g-3">${d.party.map(card)}</div>`}
  </div></div>`);
  ctx.on(outlet.querySelector('#party-refresh'), 'click', () => ctx.reload());
}

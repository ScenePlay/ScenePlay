// All battle maps by session (templates/ttrpg/maps_overview.html).
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { statusBadge } from './_common.js';

export const title = 'Battle Maps';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/battlemap/overview');
  render(outlet, html`<div class="d-flex justify-content-between align-items-center mb-3"><h3 style="color:var(--ttrpg-accent);" class="mb-0">&#9776; Battle Maps</h3></div>
  ${d.sessions.length ? d.sessions.map(sess => html`<div class="ttrpg-card p-3 mb-3">
    <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2"><div><span style="color:var(--ttrpg-accent);font-weight:600;">${sess.title}</span><span class="small text-muted ms-2">Session #${sess.session_number}</span> <span class="ms-2">${statusBadge(sess.status)}</span></div>
      <a href="/ttrpg/battlemap/session/${sess.session_id}" class="btn btn-sm btn-outline-secondary">&#9998; Manage Maps</a></div>
    <div class="row g-3">${sess.maps.map(m => html`<div class="col-sm-6 col-lg-4"><div class="p-2 rounded h-100" style="background:color-mix(in srgb, var(--sp-accent) 6%, transparent);border:1px solid ${m.is_active ? 'var(--ttrpg-accent)' : 'var(--sp-border)'};">
      ${m.bg_url ? (m.bg_is_video ? html`<video src="${m.bg_url}" style="width:100%;height:90px;object-fit:cover;border-radius:4px;margin-bottom:6px;" muted loop autoplay playsinline></video>` : html`<img src="${m.bg_url}" style="width:100%;height:90px;object-fit:cover;border-radius:4px;margin-bottom:6px;" alt="">`)
        : html`<div style="width:100%;height:90px;border-radius:4px;margin-bottom:6px;background:var(--sp-surface);display:flex;align-items:center;justify-content:center;font-size:1.8rem;color:var(--sp-muted);">&#9776;</div>`}
      <div class="d-flex justify-content-between align-items-start gap-1"><div style="min-width:0;"><div style="color:var(--ttrpg-accent);font-weight:600;font-size:.88rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${m.name}${m.is_active ? html`<span class="badge ms-1" style="font-size:.6rem;background:var(--ttrpg-accent);color:var(--sp-on-accent);">Live</span>` : ''}</div>
        <div class="small text-muted">#${m.index} &bull; ${m.grid_cols}&times;${m.grid_rows} &bull; ${m.token_count} token${m.token_count !== 1 ? 's' : ''}</div></div>
        <div class="d-flex gap-1 flex-shrink-0"><a href="/ttrpg/battlemap/session/${sess.session_id}#edit-${m.map_id}" class="btn btn-outline-secondary btn-sm" title="Edit name, grid, and background">&#9998;</a><a href="/ttrpg/battlemap/${m.map_id}/view" class="btn btn-ttrpg btn-sm">Open</a></div></div></div></div>`)}</div></div>`)
  : html`<div class="ttrpg-card p-4 text-center text-muted"><p>No maps created yet. Open a session and create maps there.</p><a href="/ttrpg/sessions" class="btn btn-ttrpg btn-sm">Go to Sessions</a></div>`}`);
}

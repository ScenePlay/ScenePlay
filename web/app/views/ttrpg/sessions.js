// Sessions list (DM) — templates/ttrpg/sessions.html.
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { statusBadge } from './_common.js';
import { toast } from '../../ui/toast.js';

export const title = 'Sessions';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/sessions');
  render(outlet, html`
  <div class="sp-page-head"><h3 style="color:var(--ttrpg-accent);">Sessions</h3><a href="/ttrpg/sessions/new" class="btn btn-ttrpg btn-sm">+ New Session</a></div>
  ${d.sessions.length ? html`<div class="ttrpg-card p-0"><div class="sp-table-scroll"><table class="table table-hover mb-0 ttrpg-table">
    <thead><tr><th>#</th><th>Title</th><th>Campaign</th><th>Date</th><th>Party</th><th>Status</th><th colspan="2"></th></tr></thead><tbody>
    ${d.sessions.map(s => html`<tr><td>${s.session_number}</td><td>${s.title}</td><td>${s.campaign_name || '—'}</td><td>${s.session_date || '—'}</td><td>${s.party_count}</td><td>${statusBadge(s.status)}</td>
      <td><a href="/ttrpg/sessions/${s.session_id}" class="btn btn-sm btn-outline-secondary">Open</a></td>
      <td><button type="button" class="btn btn-sm btn-outline-danger" data-delete="${s.session_id}" data-title="${s.title}">Delete</button></td></tr>`)}</tbody></table></div></div>`
  : html`<div class="ttrpg-card p-4 text-center"><p class="text-muted">No sessions yet.</p><a href="/ttrpg/sessions/new" class="btn btn-ttrpg">Create First Session</a></div>`}`);
  ctx.on(outlet, 'click', async e => {
    const b = e.target.closest('button[data-delete]'); if (!b) return;
    if (!confirm('Delete session ' + b.dataset.title + '?')) return;
    const r = await api.post('/ttrpg/sessions/' + b.dataset.delete + '/delete'); toast.success(r.message); ctx.reload();
  });
}

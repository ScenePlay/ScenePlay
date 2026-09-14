// Session roll log (templates/ttrpg/relay_rolls.html): the 200 most recent
// tblRollLog rows of the relay session, plus the Clear Rolls action the old
// blueprint exposed without a button.
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { toast } from '../../ui/toast.js';

export const title = 'Roll Log';

const when = ts => (ts && ts.length > 10) ? ts.slice(11, 16) : (ts || '');

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/relay/rolls');
  document.title = 'Roll Log — ScenePlay';
  render(outlet, html`<div class="row justify-content-center"><div class="col-lg-8">
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 style="color:var(--ttrpg-accent);" class="mb-0"><span class="dice-ico">&#127922;</span> Session Roll Log</h4>
      <div class="d-flex gap-2">
        ${d.session_id && d.entries.length ? html`<button type="button" class="btn btn-sm btn-outline-danger" id="rolls-clear" title="Clear the local roll history; relay rolls made before now are ignored">&#10006; Clear Rolls</button>` : ''}
        <a href="/ttrpg/relay" class="btn btn-sm btn-outline-secondary">&larr; Relay Admin</a></div></div>
    ${!d.session_id ? html`<div class="ttrpg-card p-3 text-muted">No active relay session.</div>`
    : !d.entries.length ? html`<div class="ttrpg-card p-3 text-muted">No rolls recorded for this session yet.</div>`
    : html`<div class="ttrpg-card p-0"><div class="sp-table-scroll">
      <table class="table ttrpg-table mb-0" style="font-size:.9rem;">
        <thead><tr><th>Time</th><th>Player</th><th>Roll</th><th class="text-end">Result</th><th>Breakdown</th></tr></thead>
        <tbody>${d.entries.map(e => html`<tr>
          <td class="text-muted" style="white-space:nowrap;">${when(e.rolled_at)}</td>
          <td class="fw-bold" style="color:var(--ttrpg-accent);">${e.player_name}</td>
          <td><code style="color:var(--ttrpg-text);">${e.roll_expr}</code></td>
          <td class="text-end fw-bold">${e.result}</td>
          <td class="text-muted small">${e.breakdown}</td></tr>`)}</tbody></table></div></div>
      <div class="small text-muted mt-2">Showing up to 200 most recent rolls. Max 500 stored per session.</div>`}
  </div></div>`);
  const clear = outlet.querySelector('#rolls-clear');
  if (clear) ctx.on(clear, 'click', async () => {
    if (!confirm('Clear the local roll history? Relay rolls made before now will be ignored.')) return;
    clear.disabled = true;
    try { const r = await api.post('/ttrpg/relay/clear-rolls'); if (r.message) toast.success(r.message); ctx.reload(); }
    catch (e) { clear.disabled = false; }
  });
}

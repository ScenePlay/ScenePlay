// All Characters (DM) — templates/ttrpg/characters.html.
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { hpBar, avatar, wrapIds } from './_common.js';
import { toast } from '../../ui/toast.js';

export const title = 'All Characters';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/characters?scope=all');
  render(outlet, html`
  <div class="sp-page-head"><h3 style="color:var(--ttrpg-accent);">All Characters</h3>
    <div class="d-flex align-items-center gap-2">
      ${d.sessions.length ? html`<select id="session-filter" class="form-select form-select-sm" style="width:auto;"><option value="all">All Sessions</option>
        ${d.sessions.map(s => html`<option value="${s.session_id}" ${d.active_session_id === s.session_id ? 'selected' : ''}>#${s.session_number} — ${s.title}${s.status === 'active' ? ' (active)' : ''}</option>`)}</select>` : ''}
      <a href="/ttrpg/character/new" class="btn btn-ttrpg btn-sm">+ New Character</a></div></div>
  ${d.characters.length ? html`<div class="ttrpg-card p-0"><div class="sp-table-scroll"><table class="table table-hover mb-0 ttrpg-table">
    <thead><tr><th>Name</th><th>Class</th><th>Race</th><th>Lv</th><th>HP</th><th title="AC (D&amp;D 5e) or DR (Dungeon Crawler Carl)">AC / DR</th><th>Player</th><th></th></tr></thead><tbody>
    ${d.characters.map(c => html`<tr data-char-id="${c.character_id}">
      <td><div class="d-flex align-items-center gap-2">${c.portrait_url ? avatar(c, 30) : ''}<a href="/ttrpg/character/${c.character_id}" style="color:var(--ttrpg-accent);">${c.name}</a></div></td>
      <td>${c.char_class || '—'}</td><td>${c.race || '—'}</td><td>${c.level}</td>
      <td><div style="min-width:80px;"><div class="small">${c.hp_current}/${c.hp_max}</div>${hpBar(c, 5)}</div></td>
      <td>${c.is_dcc ? 'DR ' + c.dr_total : c.ac}</td><td>${c.user_display_name}</td>
      <td><button type="button" class="btn btn-sm btn-outline-danger" data-remove="${c.character_id}" data-name="${c.name}">Remove</button></td></tr>`)}
    <tr id="no-session-chars" class="d-none"><td colspan="8" class="text-center text-muted py-3">No characters in this session's party.</td></tr></tbody></table></div></div>`
  : html`<div class="ttrpg-card p-4 text-center"><p class="text-muted">No characters yet.</p><a href="/ttrpg/character/new" class="btn btn-ttrpg">Create First Character</a></div>`}`);
  const filter = outlet.querySelector('#session-filter');
  const sessionChars = Object.fromEntries(d.sessions.map(s => [String(s.session_id), wrapIds(s.char_ids)]));
  const applyFilter = () => {
    if (!filter) return;
    const val = filter.value; let visible = 0;
    outlet.querySelectorAll('tr[data-char-id]').forEach(row => { const show = val === 'all' || (sessionChars[val] || '').includes(',' + row.dataset.charId + ','); row.classList.toggle('d-none', !show); if (show) visible++; });
    outlet.querySelector('#no-session-chars').classList.toggle('d-none', visible > 0);
  };
  if (filter) { ctx.on(filter, 'change', applyFilter); applyFilter(); }
  ctx.on(outlet, 'click', async e => {
    const b = e.target.closest('button[data-remove]'); if (!b) return;
    if (!confirm('Remove ' + b.dataset.name + '?')) return;
    const r = await api.post('/ttrpg/character/' + b.dataset.remove + '/delete'); toast.success(r.message); ctx.reload();
  });
}

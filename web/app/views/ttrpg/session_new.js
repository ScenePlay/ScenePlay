// New Session — templates/ttrpg/session_new.html.
import { html, render } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';

export const title = 'New Session';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/sessions/new-options');
  render(outlet, html`<div class="row justify-content-center"><div class="col-md-8"><div class="ttrpg-card p-4">
    <h3 style="color:var(--ttrpg-accent);">New Session</h3><div class="alert alert-danger" id="sn-error" style="display:none"></div>
    <form id="sn-form"><div class="row g-3">
      <div class="col-sm-8"><label class="form-label">Session Title *</label><input type="text" name="title" class="form-control" placeholder="The Dragon's Lair" required autofocus></div>
      <div class="col-sm-4"><label class="form-label">Session #</label><input type="number" name="session_number" class="form-control" value="1" min="1"></div>
      <div class="col-sm-6"><label class="form-label">Date</label><input type="date" name="session_date" value="${d.today}" class="form-control"></div>
      <div class="col-sm-6"><label class="form-label">Link to Campaign (optional)</label><select name="campaign_id" class="form-select"><option value="">— None —</option>${d.campaigns.map(c => html`<option value="${c.campaign_id}">${c.campaign_name}</option>`)}</select></div>
      <div class="col-sm-6"><label class="form-label">Game system</label><select name="game_system" id="gameSystem" class="form-select">${Object.entries(d.game_systems).map(([sid, gs]) => html`<option value="${sid}">${gs.name}</option>`)}</select><div class="form-text">Sets which rules the dice rollers follow while this session is live.</div></div>
      <div class="col-sm-6" id="floorWrap" style="display:none;"><label class="form-label">Current Floor</label><input type="number" name="floor" class="form-control" value="3" min="1" max="18"><div class="form-text">Dungeon Crawler Carl: target numbers are built from the Floor. Change it on the session page as the party descends.</div></div>
      <div class="col-12"><label class="form-label">Add Characters to Party</label><div class="ttrpg-card p-2" style="border-color:var(--sp-border); max-height:220px; overflow-y:auto;">
        ${d.characters.length ? d.characters.map(c => html`<div class="form-check"><input class="form-check-input" type="checkbox" name="character_ids" value="${c.character_id}" id="char_${c.character_id}"><label class="form-check-label" for="char_${c.character_id}">${c.name} <span class="text-muted small">— Lv${c.level} ${c.char_class || ''} (${c.user_display_name})</span></label></div>`) : html`<p class="text-muted small mb-0">No characters yet.</p>`}</div></div>
    </div><div class="mt-4 d-flex gap-2"><button type="submit" class="btn btn-ttrpg">Create Session</button><a href="/ttrpg/sessions" class="btn btn-outline-secondary">Cancel</a></div></form></div></div></div>`);
  ctx.on(outlet.querySelector('#gameSystem'), 'change', e => { outlet.querySelector('#floorWrap').style.display = e.target.value === 'dcc' ? '' : 'none'; });
  ctx.on(outlet.querySelector('#sn-form'), 'submit', async e => {
    e.preventDefault(); const f = e.target; const err = outlet.querySelector('#sn-error'); err.style.display = 'none';
    const body = { title: f.title.value, session_number: f.session_number.value, session_date: f.session_date.value, campaign_id: f.campaign_id.value, game_system: f.game_system.value, floor: f.floor.value,
      character_ids: [...f.querySelectorAll('input[name=character_ids]:checked')].map(i => i.value) };
    try { const r = await api.post('/api/v1/sessions', body, { quiet: true }); ctx.navigate('/ttrpg/sessions/' + r.session_id); }
    catch (x) { err.textContent = x instanceof ApiError ? x.message : String(x.message || x); err.style.display = ''; }
  });
}

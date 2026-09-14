// My Characters (player landing) — templates/ttrpg/my_characters.html.
import { html, render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { hpBar, avatar } from './_common.js';

export const title = 'My Characters';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/characters?scope=mine' + (ctx.query.all === '1' ? '&all=1' : ''));
  const chars = d.characters;
  render(outlet, html`
  <div class="sp-page-head"><h3 style="color:var(--ttrpg-accent);">My Characters</h3><a href="/ttrpg/character/new" class="btn btn-ttrpg btn-sm">+ New Character</a></div>
  ${d.active_map ? html`<div class="alert mb-3 d-flex align-items-center justify-content-between gap-3" style="background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);"><span style="color:var(--ttrpg-accent);">&#9654; A battle is in progress — <strong>${d.active_map.name}</strong></span><a href="/ttrpg/battlemap/${d.active_map.map_id}/view" class="btn btn-ttrpg btn-sm flex-shrink-0">&#9776; Open Map</a></div>` : ''}
  ${d.hidden_count && chars.length ? html`<p class="small text-muted mb-2">Showing your character${chars.length !== 1 ? 's' : ''} in the current campaign${d.campaign_name ? html` &mdash; <strong>${d.campaign_name}</strong>` : ''}. <a href="/ttrpg/my-character?all=1">Show all my characters (${d.hidden_count} more)</a></p>`
    : d.show_all ? html`<p class="small text-muted mb-2">Showing all your characters across campaigns. <a href="/ttrpg/my-character">Show only the current campaign</a></p>` : ''}
  ${chars.length ? html`<div class="row g-3">${chars.map(c => html`<div class="col-sm-6 col-md-4">
    <a href="/ttrpg/character/${c.character_id}" class="text-decoration-none"><div class="ttrpg-card p-3">
      <div class="d-flex gap-3 align-items-center">${avatar(c, 60, '8px')}<div><div class="fw-bold" style="color:var(--ttrpg-accent);">${c.name}</div><div class="small text-muted">Lv${c.level} ${c.char_class || ''} &bull; ${c.race || ''}</div><div class="small text-muted">HP ${c.hp_current}/${c.hp_max}</div></div></div>
      ${hpBar(c)}
      ${c.conditions.length ? html`<div class="d-flex flex-wrap gap-1 mt-2">${c.conditions.map(x => html`<span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);font-size:.72rem;">${x}</span>`)}</div>` : ''}
      ${c.skills.length ? html`<div class="mt-2" style="font-size:.72rem;color:var(--sp-muted);line-height:1.6;">${c.skills.map((s, i) => html`<span>${s.proficient ? '★' : ''}${s.skill_name} ${(s.bonus >= 0 ? '+' : '') + s.bonus}${i < c.skills.length - 1 ? ' ' : ''}</span>`)}</div>` : ''}
    </div></a>
    ${d.obs_enabled ? html`<a href="/ttrpg/obs/feed/${c.character_id}" class="btn btn-sm btn-outline-secondary w-100 mt-1">&#128247; My Camera${!c.has_feed ? ' — set up' : ''}</a>` : ''}
  </div>`)}</div>`
  : d.hidden_count ? html`<div class="ttrpg-card p-4 text-center"><p class="text-muted">None of your characters are in the current session's party.</p><a href="/ttrpg/my-character?all=1" class="btn btn-ttrpg mt-2">Show All My Characters</a></div>`
  : html`<div class="ttrpg-card p-4 text-center"><p class="text-muted">You don't have any characters yet.</p><a href="/ttrpg/character/new" class="btn btn-ttrpg mt-2">Create Your Character</a></div>`}`);
}

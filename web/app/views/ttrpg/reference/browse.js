// Read-only library browser for every logged-in user
// (templates/ttrpg/library_browse.html): one accordion per library with a
// per-section name filter.
import { html, render } from '../../../lib/dom.js';
import { api } from '../../../api.js';

export const title = 'Library';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/reference/library');
  render(outlet, html`
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <h3 style="color:var(--ttrpg-accent);" class="mb-0">&#128218; Library</h3>
    <span class="small text-muted">Reference only &mdash; spells, gear, feats, races &amp; more.</span></div>
  <div class="accordion" id="libAccordion">
    ${d.categories.map(c => html`<div class="accordion-item" style="background:var(--ttrpg-surface);border-color:var(--sp-border);">
      <h2 class="accordion-header"><button class="accordion-button collapsed" type="button" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);box-shadow:none;" data-bs-toggle="collapse" data-bs-target="#lib-${c.key}" aria-expanded="false" aria-controls="lib-${c.key}">
        ${c.label} <span class="badge ms-2" style="background:var(--ttrpg-accent);color:#111;">${c.items.length}</span></button></h2>
      <div id="lib-${c.key}" class="accordion-collapse collapse" data-bs-parent="#libAccordion"><div class="accordion-body">
        ${c.items.length ? html`<input type="text" class="form-control form-control-sm mb-2" placeholder="Search ${c.label}&hellip;" data-filter="list-${c.key}">
          <div id="list-${c.key}">${c.items.map(it => html`<div class="lib-item ttrpg-card p-2 mb-2" data-name="${it.name.toLowerCase()}" style="border-color:var(--sp-border);">
            <div class="fw-bold" style="color:var(--ttrpg-accent);">${it.name}</div>
            ${it.sub ? html`<div class="small text-muted">${it.sub}</div>` : ''}
            ${it.desc ? html`<div class="small mt-1" style="white-space:pre-wrap;">${it.desc}</div>` : ''}</div>`)}
          <p class="lib-empty text-muted small mb-0" style="display:none;">No matches.</p></div>`
        : html`<p class="text-muted small mb-0">Nothing in this library yet.</p>`}</div></div></div>`)}
  </div>`);
  ctx.on(outlet, 'input', e => {
    const inp = e.target.closest('input[data-filter]'); if (!inp) return;
    const q = (inp.value || '').toLowerCase().trim();
    const list = outlet.querySelector('#' + inp.dataset.filter); if (!list) return;
    let shown = 0;
    list.querySelectorAll('.lib-item').forEach(el => { const match = !q || el.dataset.name.includes(q); el.style.display = match ? '' : 'none'; if (match) shown++; });
    const empty = list.querySelector('.lib-empty'); if (empty) empty.style.display = shown ? 'none' : '';
  });
}

// Library Organizer · Artists (templates/artists_suggest.html).
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { libraryNav } from './library_nav.js';

export const title = 'Library Organizer · Artists';
const CSS = `.sp-ar table{width:100%;font-size:.85em;border-collapse:collapse}.sp-ar th,.sp-ar td{padding:4px 8px;border-bottom:1px solid var(--sp-border);vertical-align:top}.sp-ar th{text-align:left;position:sticky;top:0;background:var(--sp-surface,#fff)}.sp-ar .muted{color:var(--sp-muted)}.sp-ar .c-exact,.sp-ar .c-high{color:#2f7d38}.sp-ar .c-medium{color:#b9770e}.sp-ar .c-low{color:#c0392b}.sp-ar .scroll{max-height:65vh;overflow:auto}.sp-ar input.ar-artist{min-width:180px}`;

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/library/artists');
  const kinds = d.kinds || {};
  render(outlet, html`<style>${raw(CSS)}</style><div class="sp-page sp-ar">
    <div class="sp-page-head"><h1>Library Organizer <span class="muted" style="font-weight:normal;font-size:.6em;">· Artists</span></h1></div>
    ${libraryNav('artists')}
    <p class="muted" style="font-size:.85em;margin:4px 0 10px;">An artist for every song and video that has none, worked out from the YouTube data: <b class="c-exact">exact</b> = YouTube's own artist field (auto-generated "&ndash; Topic" uploads); <b class="c-high">high</b> = "Artist &ndash; Title" and the channel agrees; <b class="c-medium">medium</b> = the title alone says so; <b class="c-low">low</b> = only the channel name. Edit any box before applying. New downloads get the exact/high cases filled automatically. Also shown: the kind by length (song / long track / mix) and the decade where YouTube knows it.</p>
    <details class="sp-card" open><summary><h3>Proposals <span class="muted" style="font-weight:normal;font-size:.75em;">— ${d.rows.length} without an artist: ${d.counts.exact} exact, ${d.counts.high} high, ${d.counts.medium} medium, ${d.counts.low} low, ${d.counts.none} none</span></h3></summary>
      <div class="d-flex gap-2 align-items-center flex-wrap" style="margin:6px 0 8px;">
        <button type="button" class="btn btn-primary" data-apply="exact,high">&#10003; Apply exact + high (${d.counts.exact + d.counts.high})</button>
        <button type="button" class="btn btn-outline-primary" data-apply="exact,high,medium">&#10003; …and medium (${d.counts.exact + d.counts.high + d.counts.medium})</button>
        <button type="button" class="btn btn-outline-primary" data-apply="checked">&#10003; Apply checked</button>
        <label class="form-check" style="margin:0 0 0 8px;"><input class="form-check-input" type="checkbox" id="ar-check-all"> <span class="form-check-label small">check all</span></label>
        <input type="search" class="form-control form-control-sm" placeholder="Filter…" style="max-width:240px;" id="ar-filter"><span id="ar-msg" class="small muted"></span></div>
      <div class="scroll"><table id="ar-table"><thead><tr><th></th><th>Title</th><th>Channel</th><th>Artist</th><th>How</th><th>Kind</th><th>Decade</th></tr></thead><tbody>
        ${d.rows.length ? d.rows.map(r => html`<tr data-type="${r.media_type}" data-id="${r.id}" data-conf="${r.confidence}"><td><input class="form-check-input ar-pick" type="checkbox"></td>
          <td style="max-width:340px;word-break:break-word;">${r.name}${r.media_type === 'video' ? html` <span class="muted">(video)</span>` : ''}</td><td class="muted">${r.channel}</td>
          <td><input type="text" class="form-control form-control-sm ar-artist" value="${r.artist}" placeholder="(leave blank to skip)"></td>
          <td class="c-${r.confidence}">${r.confidence}${r.source ? html` <span class="muted">(${r.source})</span>` : ''}</td>
          <td class="muted">${Array.isArray(kinds) ? r.kind : (kinds[r.kind] || '')}</td><td class="muted">${r.decade}</td></tr>`)
        : html`<tr><td colspan="7" class="muted">Every song and video already has an artist.</td></tr>`}</tbody></table></div></details></div>`);
  const $ = s => outlet.querySelector(s);
  ctx.on($('#ar-check-all'), 'change', e => outlet.querySelectorAll('.ar-pick').forEach(c => { c.checked = e.target.checked; }));
  ctx.on($('#ar-filter'), 'input', e => { const q = e.target.value.trim().toLowerCase(); outlet.querySelectorAll('#ar-table tbody tr').forEach(tr => { tr.style.display = (!q || tr.textContent.toLowerCase().includes(q)) ? '' : 'none'; }); });
  ctx.on(outlet, 'click', async e => {
    const b = e.target.closest('button[data-apply]'); if (!b) return;
    const confs = b.dataset.apply === 'checked' ? null : b.dataset.apply.split(',');
    const items = [];
    outlet.querySelectorAll('#ar-table tbody tr[data-id]').forEach(tr => {
      const pick = confs ? confs.includes(tr.dataset.conf) : tr.querySelector('.ar-pick').checked;
      const artist = tr.querySelector('.ar-artist').value.trim();
      if (pick && artist) items.push({ media_type: tr.dataset.type, id: parseInt(tr.dataset.id, 10), artist });
    });
    const msg = $('#ar-msg');
    if (!items.length) { msg.textContent = 'Nothing to apply.'; return; }
    if (!confirm('Set the artist on ' + items.length + ' item' + (items.length === 1 ? '' : 's') + '?')) return;
    try { const r = await api.post('/api/artists/apply', { items }, { quiet: true }); msg.textContent = 'Updated ' + r.updated + '.'; ctx.after(900, () => ctx.reload()); }
    catch (x) { msg.textContent = x.message || 'Apply failed.'; }
  });
}

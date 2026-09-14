// Library Organizer · Genres (templates/genres_suggest.html).
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { libraryNav } from './library_nav.js';

export const title = 'Library Organizer · Genres';
const CSS = `.sp-gs table{width:100%;font-size:.85em;border-collapse:collapse}.sp-gs th,.sp-gs td{padding:4px 8px;border-bottom:1px solid var(--sp-border);vertical-align:top}.sp-gs th{text-align:left;position:sticky;top:0;background:var(--sp-surface,#fff)}.sp-gs .muted{color:var(--sp-muted)}.sp-gs .conf-scene{color:#2f7d38}.sp-gs .conf-tags{color:#b9770e}.sp-gs .conf-conflict{color:#c0392b}.sp-gs .scroll{max-height:65vh;overflow:auto}.sp-gs select{min-width:130px}`;

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/library/genres');
  render(outlet, html`<style>${raw(CSS)}</style><div class="sp-page sp-gs">
    <div class="sp-page-head"><h1>Library Organizer <span class="muted" style="font-weight:normal;font-size:.6em;">· Genres</span></h1></div>
    ${libraryNav('genres')}
    <p class="muted" style="font-size:.85em;margin:4px 0 10px;">Every song without a genre, with a proposal and the reason. <b class="conf-scene">scene</b> = the song sits in a genre-named scene (trusted); <b class="conf-tags">tags</b> = only YouTube tags/title say so (check it); <b class="conf-conflict">conflict</b> = the song sits in scenes of two different genres — you pick. A differing tag opinion is shown under the reason but never overrides the scene. Nothing is written until you apply. Genres you type that don't exist yet are created.</p>
    <details class="sp-card"><summary><h3>Scene &rarr; genre mapping <span class="muted" style="font-weight:normal;font-size:.75em;">— which scene names mean which genre</span></h3></summary>
      <p class="muted" style="font-size:.8em;">A scene named exactly like a genre needs no entry. Lower-case scene name on the left.</p>
      <textarea id="gs-map" class="form-control" rows="6" style="font-family:monospace;font-size:.8em;max-width:520px;">${JSON.stringify(d.scene_map, null, 1)}</textarea>
      <button type="button" class="btn btn-sm btn-outline-secondary mt-1" id="gs-save-map">Save mapping &amp; re-suggest</button> <span id="gs-map-msg" class="small muted"></span></details>
    <details class="sp-card" open><summary><h3>Proposals <span class="muted" style="font-weight:normal;font-size:.75em;">— ${d.rows.length} songs without a genre: ${d.counts.scene} by scene, ${d.counts.tags} by tags, ${d.counts.conflict} conflicts, ${d.counts.none} no clue</span></h3></summary>
      <div class="d-flex gap-2 align-items-center flex-wrap" style="margin:6px 0 8px;">
        <button type="button" class="btn btn-primary" data-apply="scene" title="Write every proposal whose reason is scene membership">&#10003; Apply all scene-based (${d.counts.scene})</button>
        <button type="button" class="btn btn-outline-primary" data-apply="checked">&#10003; Apply checked</button>
        <label class="form-check" style="margin:0 0 0 8px;"><input class="form-check-input" type="checkbox" id="gs-check-all"> <span class="form-check-label small">check all</span></label>
        <input type="search" class="form-control form-control-sm" placeholder="Filter…" style="max-width:240px;" id="gs-filter"><span id="gs-msg" class="small muted"></span></div>
      <div class="scroll"><table id="gs-table"><thead><tr><th></th><th>Song</th><th>Channel</th><th>Scenes</th><th>Genre</th><th>Why</th></tr></thead><tbody>
        ${d.rows.length ? d.rows.map(r => html`<tr data-song="${r.song_id}" data-conf="${r.confidence}"><td><input class="form-check-input gs-pick" type="checkbox"></td>
          <td style="max-width:320px;word-break:break-word;">${r.name}</td><td class="muted">${r.channel}</td><td class="muted">${(r.scenes || []).join(', ')}</td>
          <td><select class="form-select form-select-sm gs-genre"><option value="">(skip)</option>${d.genres.map(g => html`<option value="${g}" ${g === r.suggested ? 'selected' : ''}>${g}</option>`)}</select></td>
          <td class="conf-${r.confidence}">${r.reason || '—'}${r.alt && r.alt !== r.suggested ? html`<div class="muted">tags say ${r.alt} (${r.alt_reason})</div>` : ''}</td></tr>`)
        : html`<tr><td colspan="6" class="muted">Every song already has a genre.</td></tr>`}</tbody></table></div></details></div>`);
  const $ = s => outlet.querySelector(s);
  ctx.on($('#gs-check-all'), 'change', e => outlet.querySelectorAll('.gs-pick').forEach(c => { c.checked = e.target.checked; }));
  ctx.on($('#gs-filter'), 'input', e => { const q = e.target.value.trim().toLowerCase(); outlet.querySelectorAll('#gs-table tbody tr').forEach(tr => { tr.style.display = (!q || tr.textContent.toLowerCase().includes(q)) ? '' : 'none'; }); });
  ctx.on(outlet, 'click', async e => {
    const b = e.target.closest('button[data-apply]'); if (!b) return;
    const mode = b.dataset.apply, items = [];
    outlet.querySelectorAll('#gs-table tbody tr[data-song]').forEach(tr => {
      const pick = mode === 'scene' ? tr.dataset.conf === 'scene' : tr.querySelector('.gs-pick').checked;
      const genre = tr.querySelector('.gs-genre').value;
      if (pick && genre) items.push({ song_id: parseInt(tr.dataset.song, 10), genre });
    });
    const msg = $('#gs-msg');
    if (!items.length) { msg.textContent = 'Nothing to apply.'; return; }
    if (!confirm('Set the genre on ' + items.length + ' song' + (items.length === 1 ? '' : 's') + '?')) return;
    try { const r = await api.post('/api/genres/apply', { items }, { quiet: true }); msg.textContent = 'Updated ' + r.updated + (r.created.length ? ' — new genres: ' + r.created.join(', ') : '') + '.'; ctx.after(900, () => ctx.reload()); }
    catch (x) { msg.textContent = x.message || 'Apply failed.'; }
  });
  ctx.on($('#gs-save-map'), 'click', async () => {
    const msg = $('#gs-map-msg'); let map;
    try { map = JSON.parse($('#gs-map').value); } catch (e) { msg.textContent = 'Not valid JSON.'; return; }
    try { await api.post('/api/genres/scene-map', { map }, { quiet: true }); ctx.reload(); } catch (x) { msg.textContent = x.message || 'Save failed.'; }
  });
}

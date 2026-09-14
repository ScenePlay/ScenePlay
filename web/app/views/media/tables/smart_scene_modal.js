// Smart scene form (from scenes_table.html): a rule-driven scene built from
// other scenes, genres, artists, kinds, decades or a word.
import { api } from '../../../api.js';

const MODAL_HTML = `<div class="modal fade" id="spSmartModal" tabindex="-1"><div class="modal-dialog modal-lg"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title">New smart scene</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body">
    <p class="small text-muted" style="margin:0 0 8px;">Pick what goes in: other scenes as sources, artists, a kind, a decade, a word — from as many boxes as you like. The scene keeps its rule: new downloads that match are added automatically, and nothing you add by hand is ever removed.</p>
    <div class="small mb-2"><b>Combine picks:</b>
      <label class="ms-2"><input type="radio" name="sm-combine" value="any" checked> <b>any</b> of them <span class="text-muted">— everything in the picked scenes <i>plus</i> the picked artists <i>plus</i>…</span></label>
      <label class="ms-3"><input type="radio" name="sm-combine" value="all"> <b>all</b> of them <span class="text-muted">— only songs matching every box (e.g. Jazz <i>and</i> mixes)</span></label></div>
    <style>.sm-list{border:1px solid var(--sp-border);border-radius:4px;padding:4px 6px;overflow:auto;font-size:.85em;background:var(--sp-surface);}.sm-list label{display:block;margin:0;white-space:nowrap;cursor:pointer;}.sm-list label.picked{font-weight:600;}.sm-picked{font-size:.75em;color:var(--sp-muted);min-height:1.2em;}</style>
    <div class="d-flex gap-3 flex-wrap">
      <div><label class="small"><b>From scenes</b></label><input type="search" class="form-control form-control-sm mb-1 sm-filter" data-list="sm-scenes" placeholder="filter…" style="max-width:190px;"><div id="sm-scenes" class="sm-list" style="width:190px;height:150px;"></div><div class="sm-picked" data-for="sm-scenes"></div></div>
      <div><label class="small"><b>Genre</b> <span class="text-muted" title="From the YouTube tags, title and channel (or a label you set on the music table)">from metadata</span></label><div id="sm-genres" class="sm-list" style="width:170px;height:150px;"></div><div class="sm-picked" data-for="sm-genres"></div></div>
      <div><label class="small"><b>Artists</b></label><input type="search" class="form-control form-control-sm mb-1 sm-filter" data-list="sm-artists" placeholder="filter…" style="max-width:190px;"><div id="sm-artists" class="sm-list" style="width:190px;height:150px;"></div><div class="sm-picked" data-for="sm-artists"></div>
        <button type="button" class="btn btn-sm btn-outline-secondary mt-1" style="font-size:.72rem;" id="sm-build" title="Work out the artist for every song and video that has none, from its YouTube title / channel / artist field. Sure cases only; safe to repeat.">&#9881; Build from metadata</button>
        <button type="button" class="btn btn-sm btn-outline-secondary mt-1" style="font-size:.72rem;" id="sm-build-med" title="Also take the title-only guesses (Artist – Title with no channel confirmation). Fix any wrong ones in the music table's Artist column.">&#9881; …incl. guesses</button>
        <div id="sm-build-msg" class="small text-muted"></div></div>
      <div><label class="small"><b>Kind</b></label><div id="sm-kinds" class="sm-list" style="width:170px;"></div><label class="small mt-2"><b>Decade</b></label><div id="sm-decades" class="sm-list" style="width:170px;max-height:110px;"></div></div>
      <div><label class="small"><b>Word in title / channel</b></label><input type="text" id="sm-text" class="form-control form-control-sm" style="max-width:170px;"><div class="mt-2 small"><label><input type="checkbox" id="sm-music" checked> music</label> &nbsp; <label><input type="checkbox" id="sm-video" checked> videos</label></div></div>
    </div>
    <div id="sm-count" class="small mt-2 text-muted">Pick something to see how many match.</div>
    <div class="d-flex gap-2 align-items-end flex-wrap mt-2">
      <div><label class="small">Scene name</label><input type="text" id="sm-name" class="form-control form-control-sm" style="min-width:240px;"></div>
      <div><label class="small">Campaign</label><select id="sm-campaign" class="form-select form-select-sm"></select></div>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="sm-reset">&#8634; Reset</button></div>
  </div>
  <div class="modal-footer"><span id="sm-msg" class="small text-muted me-auto"></span><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-primary" id="sm-create">Create scene</button></div>
</div></div></div>`;

let _wired = false, _onCreated = null, _timer = null;
const $ = id => document.getElementById(id);

function rule() {
  const sel = id => [...document.querySelectorAll('#' + id + ' input:checked')].map(i => i.value);
  const media = []; if ($('sm-music').checked) media.push('music'); if ($('sm-video').checked) media.push('video');
  const combine = (document.querySelector('input[name="sm-combine"]:checked') || {}).value || 'any';
  return { scenes: sel('sm-scenes'), genres: sel('sm-genres'), artists: sel('sm-artists'), kinds: sel('sm-kinds'), decades: sel('sm-decades'), text: $('sm-text').value, media, combine };
}
function count() {
  clearTimeout(_timer);
  _timer = setTimeout(() => {
    const r = rule();
    if (!r.scenes.length && !r.genres.length && !r.artists.length && !r.kinds.length && !r.decades.length && !r.text.trim()) { $('sm-count').textContent = 'Pick something to see how many match.'; return; }
    api.post('/api/smart-scenes/preview', { rule: r }, { quiet: true }).then(d => { $('sm-count').textContent = d.summary + ' — ' + d.music.length + ' songs, ' + d.video.length + ' videos'; }).catch(() => {});
  }, 250);
}
function pickedLine(id) { const el = document.querySelector('.sm-picked[data-for="' + id + '"]'); if (!el) return; const picked = [...document.querySelectorAll('#' + id + ' input:checked')].map(i => i.value); el.textContent = picked.length ? 'picked: ' + picked.join(', ') : ''; }
function fill(id, list, label) {
  const s = $(id); s.innerHTML = '';
  (list || []).forEach(o => {
    const l = document.createElement('label'); const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = o.value; cb.className = 'form-check-input me-1';
    cb.onchange = () => { l.classList.toggle('picked', cb.checked); pickedLine(id); count(); };
    l.appendChild(cb); l.appendChild(document.createTextNode((label ? o.label : o.value) + ' (' + o.count + ')')); s.appendChild(l);
  });
}
function reset() {
  ['sm-scenes', 'sm-genres', 'sm-artists', 'sm-kinds', 'sm-decades'].forEach(id => { document.querySelectorAll('#' + id + ' input').forEach(i => { i.checked = false; }); document.querySelectorAll('#' + id + ' label').forEach(l => { l.classList.remove('picked'); l.style.display = ''; }); pickedLine(id); });
  document.querySelectorAll('.sm-filter').forEach(f => { f.value = ''; });
  $('sm-text').value = ''; $('sm-name').value = '';
  const anyR = document.querySelector('input[name="sm-combine"][value="any"]'); if (anyR) anyR.checked = true;
  $('sm-music').checked = true; $('sm-video').checked = true;
  $('sm-count').textContent = 'Pick something to see how many match.'; $('sm-msg').textContent = '';
}
function buildArtists(includeMedium) {
  const msg = $('sm-build-msg'); msg.textContent = 'Building…';
  api.post('/api/artists/build', { include_medium: includeMedium }, { quiet: true }).then(d => {
    if (!d.ok) { msg.textContent = d.error || 'Failed.'; return; }
    msg.textContent = 'Set ' + d.updated + ' artist' + (d.updated === 1 ? '' : 's') + (d.left.medium ? ' — ' + d.left.medium + ' guesses left (use "…incl. guesses")' : '') + '.';
    const keep = new Set([...document.querySelectorAll('#sm-artists input:checked')].map(i => i.value));
    api.get('/api/smart-scenes/facets', { quiet: true }).then(f => { fill('sm-artists', f.options.artists); document.querySelectorAll('#sm-artists input').forEach(cb => { if (keep.has(cb.value)) { cb.checked = true; cb.parentNode.classList.add('picked'); } }); pickedLine('sm-artists'); });
  }).catch(() => { msg.textContent = 'Failed.'; });
}
function create() {
  const msg = $('sm-msg'); const name = $('sm-name').value.trim();
  if (!name) { msg.textContent = 'Give the scene a name.'; return; }
  api.post('/api/smart-scenes/create', { name, campaign_id: $('sm-campaign').value, rule: rule(), auto_refresh: true }, { quiet: true }).then(d => {
    if (!d.ok) { msg.textContent = d.error || 'Failed.'; return; }
    msg.textContent = 'Created with ' + d.added.music + ' songs, ' + d.added.video + ' videos.';
    setTimeout(() => { window.bootstrap.Modal.getOrCreateInstance($('spSmartModal')).hide(); if (_onCreated) _onCreated(d); }, 800);
  }).catch(() => { msg.textContent = 'Failed.'; });
}

export function openSmartSceneForm(onCreated) {
  _onCreated = onCreated;
  if (!$('spSmartModal')) document.body.insertAdjacentHTML('beforeend', MODAL_HTML);
  const m = $('spSmartModal');
  if (!_wired) {
    _wired = true;
    $('sm-text').oninput = count; $('sm-music').onchange = count; $('sm-video').onchange = count;
    document.querySelectorAll('input[name="sm-combine"]').forEach(r => r.onchange = count);
    document.querySelectorAll('.sm-filter').forEach(f => f.oninput = function () { const q = this.value.trim().toLowerCase(); document.querySelectorAll('#' + this.dataset.list + ' label').forEach(l => { l.style.display = (!q || l.textContent.toLowerCase().includes(q)) ? '' : 'none'; }); });
    $('sm-reset').onclick = reset; $('sm-create').onclick = create;
    $('sm-build').onclick = () => buildArtists(false); $('sm-build-med').onclick = () => buildArtists(true);
  }
  api.get('/api/smart-scenes/facets', { quiet: true }).then(d => {
    fill('sm-scenes', d.options.scenes); fill('sm-genres', d.options.genres); fill('sm-artists', d.options.artists); fill('sm-kinds', d.options.kinds, true); fill('sm-decades', d.options.decades);
    const c = $('sm-campaign'); c.innerHTML = ''; d.campaigns.forEach(x => { const e = document.createElement('option'); e.value = x.id; e.textContent = x.name; if (x.name === 'Music') e.selected = true; c.appendChild(e); });
    reset();
    window.bootstrap.Modal.getOrCreateInstance(m).show();
  }).catch(() => alert('Could not load the pickers.'));
}

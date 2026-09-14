// Library Organizer · Smart Scenes (templates/smart_scenes.html).
import { html, render, raw, esc } from '../../lib/dom.js';
import { api } from '../../api.js';
import { libraryNav } from './library_nav.js';

export const title = 'Library Organizer · Smart Scenes';
const CSS = `.sp-ss .muted{color:var(--sp-muted)}.sp-ss .facet{display:flex;flex-direction:column;gap:2px;min-width:180px}.sp-ss .facet select[multiple]{min-height:150px;font-size:.85em}.sp-ss table{width:100%;font-size:.85em;border-collapse:collapse}.sp-ss th,.sp-ss td{padding:4px 8px;border-bottom:1px solid var(--sp-border);vertical-align:top}.sp-ss th{text-align:left}.sp-ss .preview{max-height:32vh;overflow:auto;font-size:.82em}`;

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/library/smart-scenes');
  const o = d.options;
  const campSel = id => html`<select id="${id}" class="form-select form-select-sm">${d.campaigns.map(c => html`<option value="${c[0]}" ${c[1] === 'Music' ? 'selected' : ''}>${c[1]}</option>`)}</select>`;
  render(outlet, html`<style>${raw(CSS)}</style><div class="sp-page sp-ss">
    <div class="sp-page-head"><h1>Library Organizer <span class="muted" style="font-weight:normal;font-size:.6em;">· Smart Scenes</span></h1></div>
    ${libraryNav('scenes')}
    <p class="muted" style="font-size:.85em;margin:4px 0 10px;">A smart scene fills itself from your library by metadata: pick any mix of genre, artist, kind (song / long track / mix), decade and a word in the title, see what matches, and create the scene. It keeps its rule: new downloads that match are added automatically, and <b>Refresh</b> re-checks any time. Songs you add by hand are never removed. Genres come from Suggest Genres, artists from the Artists page — run those first for the best pickers.</p>
    <details class="sp-card" open><summary><h3>Build a scene</h3></summary>
      <div class="d-flex gap-3 flex-wrap" style="margin:8px 0;">
        <div class="facet"><label class="small"><b>Genre</b> <span class="muted">(any of)</span></label><select id="f-genres" multiple>${o.genres.map(x => html`<option value="${x.value}">${x.value} (${x.count})</option>`)}</select></div>
        <div class="facet"><label class="small"><b>Artist</b> <span class="muted">(any of)</span></label><input type="search" class="form-control form-control-sm" placeholder="filter artists…" id="f-artist-filter"><select id="f-artists" multiple>${o.artists.map(x => html`<option value="${x.value}">${x.value} (${x.count})</option>`)}</select></div>
        <div class="facet"><label class="small"><b>Kind</b></label><select id="f-kinds" multiple style="min-height:80px;">${o.kinds.map(x => html`<option value="${x.value}">${x.label} (${x.count})</option>`)}</select>
          <label class="small mt-2"><b>Decade</b></label><select id="f-decades" multiple style="min-height:80px;">${o.decades.map(x => html`<option value="${x.value}">${x.value} (${x.count})</option>`)}</select></div>
        <div class="facet"><label class="small"><b>Word in title / channel</b></label><input type="text" id="f-text" class="form-control form-control-sm" placeholder="e.g. coffee">
          <label class="small mt-2"><b>Draw from</b></label>
          <label class="form-check small" style="margin:0;"><input class="form-check-input" type="checkbox" id="f-music" checked> <span class="form-check-label">Music</span></label>
          <label class="form-check small" style="margin:0;"><input class="form-check-input" type="checkbox" id="f-video" checked> <span class="form-check-label">Videos</span></label>
          <div class="d-flex gap-1 mt-2"><button type="button" class="btn btn-sm btn-outline-secondary" id="ss-preview-btn">&#128269; Preview matches</button><button type="button" class="btn btn-sm btn-outline-secondary" id="ss-reset" title="Clear every selection, the filters, the preview and the name">&#8634; Reset</button></div></div>
      </div>
      <div id="ss-summary" class="small muted" style="margin:4px 0;"></div><div id="ss-preview" class="preview"></div>
      <div class="d-flex gap-2 align-items-end flex-wrap" style="margin-top:10px;">
        <div><label class="small">Scene name</label><input type="text" id="ss-name" class="form-control form-control-sm" placeholder="e.g. Jazz · Coffee mixes" style="min-width:240px;"></div>
        <div><label class="small">Campaign</label>${campSel('ss-campaign')}</div>
        <label class="form-check small" style="margin:0 0 6px;"><input class="form-check-input" type="checkbox" id="ss-auto" checked> <span class="form-check-label">Add new downloads automatically</span></label>
        <button type="button" class="btn btn-primary btn-sm" id="ss-create">&#10003; Create smart scene</button>
        <span class="muted small">or make an existing scene smart:</span>
        <select id="ss-existing" class="form-select form-select-sm" style="max-width:220px;"><option value="">(choose scene)</option>${d.scenes.map(s => html`<option value="${s[0]}">${s[1]}</option>`)}</select>
        <button type="button" class="btn btn-outline-primary btn-sm" id="ss-attach">Attach rule</button><span id="ss-msg" class="small muted"></span></div></details>
    <details class="sp-card"><summary><h3>Bulk: one scene per artist or genre</h3></summary>
      <div class="d-flex gap-2 align-items-end flex-wrap" style="margin:8px 0;">
        <div><label class="small">One scene per</label><select id="bk-by" class="form-select form-select-sm"><option value="artist">artist</option><option value="genre">genre</option></select></div>
        <div><label class="small">with at least</label><input type="number" id="bk-min" class="form-control form-control-sm" value="4" min="1" style="width:80px;"></div>
        <div><label class="small">Campaign</label>${campSel('bk-campaign')}</div>
        <div><label class="small">Name pattern</label><input type="text" id="bk-name" class="form-control form-control-sm" value="{value}" style="width:160px;" title="{value} is the artist / genre"></div>
        <button type="button" class="btn btn-outline-primary btn-sm" id="bk-go">Create scenes</button><span id="bk-msg" class="small muted"></span></div>
      <p class="muted small" style="margin:0;">Scenes whose name already exists in that campaign are skipped, so this is safe to run again later.</p></details>
    <details class="sp-card" open><summary><h3>Smart scenes <span class="muted" style="font-weight:normal;font-size:.75em;">— ${d.rules.length}</span></h3></summary>
      <div class="d-flex gap-2 align-items-center" style="margin:6px 0;"><button type="button" class="btn btn-sm btn-outline-secondary" data-refresh="all">&#8635; Refresh all</button><span id="rl-msg" class="small muted"></span></div>
      <table><thead><tr><th>Scene</th><th>Campaign</th><th>Rule</th><th>Songs</th><th>Videos</th><th>Auto</th><th>Last refresh</th><th></th></tr></thead><tbody>
        ${d.rules.length ? d.rules.map(r => html`<tr data-scene="${r.scene_id}"><td><b>${r.name}</b></td><td class="muted">${r.campaign}</td><td>${r.summary}</td><td>${r.music}</td><td>${r.video}</td><td>${r.auto_refresh ? '✓' : '—'}</td>
          <td class="muted">${r.last_refresh}${r.last_added ? ` (+${r.last_added})` : ''}</td>
          <td style="white-space:nowrap;"><button type="button" class="btn btn-sm btn-outline-secondary" data-refresh="${r.scene_id}">&#8635; Refresh</button> <button type="button" class="btn btn-sm btn-outline-danger" data-drop="${r.scene_id}" data-name="${r.name}" title="Stop deriving members — the scene and its songs stay">Unlink rule</button></td></tr>`)
        : html`<tr><td colspan="8" class="muted">No smart scenes yet.</td></tr>`}</tbody></table></details></div>`);
  const $ = s => outlet.querySelector(s);
  const sel = id => [...$('#' + id).selectedOptions].map(x => x.value);
  const rule = () => { const media = []; if ($('#f-music').checked) media.push('music'); if ($('#f-video').checked) media.push('video'); return { genres: sel('f-genres'), artists: sel('f-artists'), kinds: sel('f-kinds'), decades: sel('f-decades'), text: $('#f-text').value, media }; };
  ctx.on($('#f-artist-filter'), 'input', e => { const q = e.target.value.trim().toLowerCase(); [...$('#f-artists').options].forEach(x => { x.hidden = !!q && !x.textContent.toLowerCase().includes(q); }); });
  ctx.on($('#ss-reset'), 'click', () => { ['f-genres', 'f-artists', 'f-kinds', 'f-decades'].forEach(id => [...$('#' + id).options].forEach(x => { x.selected = false; x.hidden = false; })); $('#f-artist-filter').value = ''; $('#f-text').value = ''; $('#f-music').checked = true; $('#f-video').checked = true; $('#ss-name').value = ''; $('#ss-existing').value = ''; $('#ss-summary').textContent = ''; $('#ss-preview').innerHTML = ''; $('#ss-msg').textContent = ''; });
  ctx.on($('#ss-preview-btn'), 'click', async () => {
    const box = $('#ss-preview'), sum = $('#ss-summary'); box.textContent = 'Matching…';
    try { const r = await api.post('/api/smart-scenes/preview', { rule: rule() }, { quiet: true });
      sum.textContent = r.summary + ' — ' + r.music.length + ' song' + (r.music.length === 1 ? '' : 's') + ', ' + r.video.length + ' video' + (r.video.length === 1 ? '' : 's');
      box.innerHTML = (r.music.map(m => '&#9835; ' + esc(m.name)).concat(r.video.map(v => '&#9654; ' + esc(v.name))).join('<br>')) || '<span class="muted">Nothing matches.</span>';
    } catch (x) { box.textContent = 'Preview failed.'; }
  });
  const msgAndReload = (msg, text) => { msg.textContent = text; ctx.after(900, () => ctx.reload()); };
  ctx.on($('#ss-create'), 'click', async () => {
    const msg = $('#ss-msg'), name = $('#ss-name').value.trim();
    if (!name) { msg.textContent = 'Give the scene a name.'; return; }
    try { const r = await api.post('/api/smart-scenes/create', { name, campaign_id: $('#ss-campaign').value, rule: rule(), auto_refresh: $('#ss-auto').checked }, { quiet: true }); msgAndReload(msg, 'Created with ' + r.added.music + ' songs, ' + r.added.video + ' videos.'); }
    catch (x) { msg.textContent = x.message || 'Failed.'; }
  });
  ctx.on($('#ss-attach'), 'click', async () => {
    const msg = $('#ss-msg'), sid = $('#ss-existing').value;
    if (!sid) { msg.textContent = 'Choose a scene to attach the rule to.'; return; }
    try { const r = await api.post('/api/smart-scenes/create', { scene_id: sid, rule: rule(), auto_refresh: $('#ss-auto').checked }, { quiet: true }); msgAndReload(msg, 'Rule attached; added ' + r.added.music + ' songs, ' + r.added.video + ' videos.'); }
    catch (x) { msg.textContent = x.message || 'Failed.'; }
  });
  ctx.on($('#bk-go'), 'click', async () => {
    const msg = $('#bk-msg'), by = $('#bk-by').value, min = $('#bk-min').value;
    if (!confirm('Create one scene per ' + by + ' with at least ' + min + ' matches?')) return;
    try { const r = await api.post('/api/smart-scenes/bulk', { by, min_count: min, campaign_id: $('#bk-campaign').value, name_format: $('#bk-name').value }, { quiet: true });
      msgAndReload(msg, 'Created ' + r.made.length + ' scene' + (r.made.length === 1 ? '' : 's') + (r.made.length ? ': ' + r.made.map(m => m.name + ' (' + m.count + ')').join(', ') : '') + '.'); }
    catch (x) { msg.textContent = x.message || 'Failed.'; }
  });
  ctx.on(outlet, 'click', async e => {
    const rf = e.target.closest('button[data-refresh]'), dr = e.target.closest('button[data-drop]'); const msg = $('#rl-msg');
    if (rf) { try { await api.post('/api/smart-scenes/refresh', rf.dataset.refresh === 'all' ? { all: true } : { scene_id: Number(rf.dataset.refresh) }, { quiet: true }); msgAndReload(msg, 'Refreshed.'); } catch (x) { msg.textContent = 'Refresh failed.'; } }
    else if (dr) { if (!confirm('Stop deriving "' + dr.dataset.name + '" from its rule? The scene and everything in it stay.')) return; await api.post('/api/smart-scenes/drop', { scene_id: Number(dr.dataset.drop) }, { quiet: true }); ctx.reload(); }
  });
}

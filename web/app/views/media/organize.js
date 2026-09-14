// Library Organizer · Organize (templates/organize.html).
import { html, render, raw, esc } from '../../lib/dom.js';
import { api } from '../../api.js';
import { libraryNav } from './library_nav.js';

export const title = 'Library Organizer';
const CSS = `.sp-org .muted{color:var(--sp-muted)}.sp-org .opts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px 24px;font-size:.9em}.sp-org .opts label.form-check{margin:0}.sp-org .plan{font-size:.9em}.sp-org .plan h4{font-size:1em;margin:10px 0 4px}.sp-org .chips span{display:inline-block;border:1px solid var(--sp-border);border-radius:12px;padding:1px 8px;margin:2px 3px 2px 0;font-size:.85em}.sp-org .chips .attached{border-color:#b9770e}.sp-org .chips .skipped{opacity:.55}`;

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/library/organize');
  render(outlet, html`<style>${raw(CSS)}</style><div class="sp-page sp-org">
    <div class="sp-page-head"><h1>Library Organizer <span class="muted" style="font-weight:normal;font-size:.6em;">· Organize</span></h1></div>
    ${libraryNav('organize')}
    <p class="muted" style="font-size:.85em;margin:4px 0 10px;">One function that does the whole job: label genres (from the scenes you built), label artists (from the YouTube data), then create a smart scene per genre and per artist — and refresh them all. Trusted derivations only, unless you tick the wider options. <b>Preview</b> shows exactly what will happen; nothing is written until <b>Run</b>. The individual pages (Suggest Genres, Artists, Smart Scenes) stay for reviewing the leftovers.</p>
    <details class="sp-card" open><summary><h3>Options</h3></summary>
      <div class="opts" style="margin:8px 0;">
        <div><b>1 · Genres</b><label class="form-check"><input class="form-check-input" type="checkbox" id="o-genres" checked> <span class="form-check-label">Label songs by the genre-named scene they sit in</span></label><label class="form-check"><input class="form-check-input" type="checkbox" id="o-genres-tags"> <span class="form-check-label">…also where only YouTube tags say so <span class="muted">(less certain)</span></span></label></div>
        <div><b>2 · Artists</b><label class="form-check"><input class="form-check-input" type="checkbox" id="o-artists" checked> <span class="form-check-label">Set artists that are exact or channel-confirmed</span></label><label class="form-check"><input class="form-check-input" type="checkbox" id="o-artists-medium"> <span class="form-check-label">…also title-only derivations <span class="muted">(check the Artists page first)</span></span></label></div>
        <div><b>3 · Smart scenes</b><label class="form-check"><input class="form-check-input" type="checkbox" id="o-genre-scenes" checked> <span class="form-check-label">One per genre with at least <input type="number" id="o-genre-min" value="3" min="1" style="width:56px;" class="form-control form-control-sm d-inline-block"> items</span></label><label class="form-check"><input class="form-check-input" type="checkbox" id="o-artist-scenes" checked> <span class="form-check-label">One per artist with at least <input type="number" id="o-artist-min" value="4" min="1" style="width:56px;" class="form-control form-control-sm d-inline-block"> items</span></label><label class="form-check"><input class="form-check-input" type="checkbox" id="o-attach" checked> <span class="form-check-label">A scene with that name already there? Make <i>it</i> smart instead of duplicating</span></label></div>
        <div><b>Where &amp; what</b><div>Campaign: <select id="o-campaign" class="form-select form-select-sm d-inline-block" style="width:auto;">${d.campaigns.map(c => html`<option value="${c[0]}" ${c[1] === 'Music' ? 'selected' : ''}>${c[1]}</option>`)}</select></div>
          <label class="form-check"><input class="form-check-input" type="checkbox" id="o-music" checked> <span class="form-check-label">Music</span></label><label class="form-check"><input class="form-check-input" type="checkbox" id="o-video" checked> <span class="form-check-label">Videos</span></label></div>
      </div>
      <div class="d-flex gap-2 align-items-center flex-wrap"><button type="button" class="btn btn-outline-primary" id="org-preview">&#128269; Preview plan</button><button type="button" class="btn btn-primary" id="org-run" disabled title="Preview first">&#9654; Run</button><span id="org-msg" class="small muted"></span></div></details>
    <details class="sp-card" open id="org-plan-card" style="display:none;"><summary><h3 id="org-plan-title">Plan</h3></summary><div id="org-plan" class="plan"></div></details></div>`);
  const g = id => outlet.querySelector('#' + id);
  const options = () => { const media = []; if (g('o-music').checked) media.push('music'); if (g('o-video').checked) media.push('video');
    return { genres: g('o-genres').checked, genres_include_tags: g('o-genres-tags').checked, artists: g('o-artists').checked, artists_include_medium: g('o-artists-medium').checked,
      scenes: g('o-genre-scenes').checked || g('o-artist-scenes').checked, genre_scenes: g('o-genre-scenes').checked, artist_scenes: g('o-artist-scenes').checked,
      genre_min: g('o-genre-min').value, artist_min: g('o-artist-min').value, campaign_id: g('o-campaign').value, media, attach_existing: g('o-attach').checked }; };
  const chips = list => !list || !list.length ? '<span class="muted">none</span>' : '<div class="chips">' + list.map(s => '<span class="' + esc(s.action) + '" title="' + esc(s.action) + '">' + esc(s.name) + ' (' + s.count + ')' + (s.action === 'attached' ? ' · attach' : s.action === 'skipped' ? ' · exists' : '') + '</span>').join('') + '</div>';
  const show = r => {
    const dry = r.dry_run; let h = '';
    if (r.genres) { const b = r.genres.by_confidence; h += '<h4>1 · Genres</h4>' + (dry ? ('Will label <b>' + r.genres.apply + '</b> songs' + (r.genres.names.length ? ' as ' + esc(r.genres.names.join(', ')) : '')) : ('Labelled <b>' + r.genres.applied + '</b> songs' + (r.genres.created_genres.length ? ' — new genres: ' + esc(r.genres.created_genres.join(', ')) : ''))) + ' <span class="muted">(' + b.scene + ' by scene, ' + b.tags + ' by tags only, ' + b.conflict + ' conflicts, ' + b.none + ' no clue — leftovers on Suggest Genres)</span>'; }
    if (r.artists) { const b = r.artists.by_confidence; h += '<h4>2 · Artists</h4>' + (dry ? 'Will set <b>' + r.artists.apply + '</b> artists' : 'Set <b>' + r.artists.applied + '</b> artists') + ' <span class="muted">(' + b.exact + ' exact, ' + b.high + ' high, ' + b.medium + ' medium, ' + b.low + ' low, ' + b.none + ' none — leftovers on Artists)</span>'; }
    if (r.scenes) { const count = (l, a) => (l || []).filter(s => s.action === a).length; h += '<h4>3 · Smart scenes</h4>';
      if (r.scenes.genres) h += '<div><b>Per genre</b> — ' + count(r.scenes.genres, 'created') + ' new, ' + count(r.scenes.genres, 'attached') + ' attached, ' + count(r.scenes.genres, 'skipped') + ' already there' + chips(r.scenes.genres) + '</div>';
      if (r.scenes.artists) h += '<div style="margin-top:6px;"><b>Per artist</b> — ' + count(r.scenes.artists, 'created') + ' new, ' + count(r.scenes.artists, 'attached') + ' attached, ' + count(r.scenes.artists, 'skipped') + ' already there' + chips(r.scenes.artists) + '</div>';
      if (dry) h += '<div class="muted small" style="margin-top:4px;">Counts use today\'s labels — with steps 1–2 on, the run can produce a few more.</div>'; }
    if (!dry && r.refreshed) h += '<h4>4 · Refresh</h4>' + r.refreshed.scenes + ' smart scenes refreshed, <b>' + r.refreshed.links + '</b> links added.';
    g('org-plan').innerHTML = h; g('org-plan-title').textContent = dry ? 'Plan (nothing written yet)' : 'Done'; g('org-plan-card').style.display = '';
  };
  const go = async dry => {
    const msg = g('org-msg');
    if (!dry && !confirm('Run the plan now? Genres and artists are written, scenes created/attached, and smart scenes refreshed.')) return;
    msg.textContent = dry ? 'Planning…' : 'Running…';
    try { const r = await api.post('/api/library/organize', { dry_run: dry, options: options() }, { quiet: true }); show(r); msg.textContent = dry ? 'Preview ready — Run when happy.' : 'Done.'; g('org-run').disabled = !dry; }
    catch (x) { msg.textContent = x.message || 'Failed.'; }
  };
  ctx.on(g('org-preview'), 'click', () => go(true));
  ctx.on(g('org-run'), 'click', () => go(false));
}

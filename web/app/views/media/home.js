// Home: campaign selector + one card per scene (templates/home.html).
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { toast } from '../../ui/toast.js';
import { store } from '../../store.js';

export const title = 'Scenes';

function cardHtml(item) {
  const c1 = item.color || '148,163,184', c2 = item.color1 || item.color || '148,163,184';
  const hasMedia = item.songs || item.videos;
  const statsTitle = `${item.songs || 0} song${item.songs === 1 ? '' : 's'}${item.videos ? `, ${item.videos} video${item.videos === 1 ? '' : 's'}` : ''}${item.play_time ? ` — about ${item.play_time} of playback (counting loops; tracks still waiting for metadata add no time)` : ''}`;
  return html`<a href="/activatescenes/?id=${item.scene_ID}" class="sp-scene-card" draggable="true" data-scene-id="${item.scene_ID}" style="--c1:${c1};--c2:${c2};">
    <span class="sp-scene-band"></span>
    <span class="sp-scene-name">${item.sceneName}</span>
    ${hasMedia ? html`<button type="button" class="sp-scene-queue" data-scene="${item.scene_ID}" data-state="${item.queued || ''}" title="Add this scene's songs to what's playing now (does not switch scene). Click again to take them out.">
        <span class="sp-scene-queue-on">&#10003; Queued</span><span class="sp-scene-queue-off">&#43; Queue</span><span class="sp-scene-queue-some">&#9681; Partly queued</span></button>
      <span class="sp-scene-stats" title="${statsTitle}">${item.songs ? raw('&#9835;&nbsp;' + item.songs) : ''}${item.videos ? raw(' &#9654;&nbsp;' + item.videos) : ''}${item.play_time ? html` <span class="sp-scene-time">&#9201;&nbsp;${item.play_time}</span>` : ''}</span>` : ''}
    ${(item.modelName != null || item.effectName != null) ? html`<span class="sp-scene-leds">${item.modelName != null ? html`<span class="sp-led-tag" title="RPi LED pattern">R&nbsp;${item.modelName}</span>` : ''}${item.effectName != null ? html`<span class="sp-led-tag" title="WLED effect">W&nbsp;${item.effectName}</span>` : ''}</span>` : ''}
  </a>`;
}

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/home');
  render(outlet, html`<div class="sp-page">
    <div class="sp-page-head sp-head-start"><h1>Scenes</h1>
      <div class="sp-filter-row">
        <label for="campaignDropdown">Campaign</label>
        <select id="campaignDropdown" class="form-select"><option value="0">All</option>
          ${d.campaigns.map(c => html`<option value="${c[0]}" ${c[0] === d.campaign_selected ? 'selected' : ''}>${c[1]}</option>`)}</select>
        <label for="sceneSort" style="margin-left:10px;">Sort</label>
        <select id="sceneSort" class="form-select"><option value="order">Play order</option><option value="name">Name</option></select>
        <span id="sceneDragHint" class="small" style="color:var(--sp-muted);margin-left:8px;">drag cards to reorder</span>
      </div></div>
    <div id="sp-mix-bar" class="gap-2 align-items-center flex-wrap" style="display:none;margin:0 0 10px;">
      <span class="small" id="sp-mix-label"></span>
      <input type="text" id="sp-mix-name" class="form-control form-control-sm" placeholder="scene name (blank = the scene names joined)" style="max-width:300px;">
      <button type="button" class="btn btn-sm btn-primary" id="sp-mix-save">&#128190; Save this mix as a scene</button>
      <span id="sp-mix-msg" class="small text-muted"></span></div>
    <div class="sp-card-grid sp-scene-grid">${d.scenes.map(cardHtml)}</div>
  </div>`);

  const grid = outlet.querySelector('.sp-scene-grid');
  const picked = new Set();
  const $ = s => outlet.querySelector(s);

  const mixBar = () => {
    const names = [...outlet.querySelectorAll('.sp-scene-queue')]
      .filter(b => picked.has(b.dataset.scene) && (b.dataset.state === 'all' || b.dataset.state === 'some'))
      .map(b => b.closest('.sp-scene-card').querySelector('.sp-scene-name').textContent.trim());
    const bar = $('#sp-mix-bar'); if (!bar) return;
    bar.style.display = names.length >= 2 ? 'flex' : 'none';
    $('#sp-mix-label').textContent = names.length >= 2 ? 'Playing a mix of ' + names.join(' + ') + ':' : '';
  };
  const applyStates = states => { outlet.querySelectorAll('.sp-scene-queue').forEach(b => { b.dataset.state = states[b.dataset.scene] || 'none'; }); mixBar(); };

  // campaign selector -> reload cards
  ctx.on($('#campaignDropdown'), 'change', async e => {
    await api.post('/api/campaignSelect', { campaign_id: e.target.value }, { quiet: true });
    store.patch('health', { relay: { on: false }, led_remote: { failing: false }, wled: { failing: false } });
    ctx.reload();
  });
  ctx.on($('#campaignDropdown'), 'click', () => { api.post('/api/alertsClear', null, { quiet: true }).catch(() => {}); });

  // queue toggles + activation (delegated on the grid)
  ctx.on(grid, 'click', async e => {
    const qb = e.target.closest('.sp-scene-queue');
    if (qb) {
      e.preventDefault(); e.stopPropagation();
      const want = qb.dataset.state !== 'all';
      if (want) picked.add(qb.dataset.scene); else picked.delete(qb.dataset.scene);
      qb.disabled = true;
      try { const r = await api.post('/api/scenes/queue', { scene_ID: parseInt(qb.dataset.scene, 10), queued: want }, { quiet: true }); if (r.ok) qb.dataset.state = r.queued || 'none'; mixBar(); }
      catch (x) {} finally { qb.disabled = false; }
      return;
    }
    const card = e.target.closest('.sp-scene-card');
    if (card) {
      e.preventDefault();
      if (dragged) { dragged = false; return; }
      card.classList.add('sp-activating');
      try { await api.post('/activatescenes/?id=' + card.dataset.sceneId, null, { quiet: true }); toast.success('Scene: ' + card.querySelector('.sp-scene-name').textContent.trim()); }
      catch (x) { toast.error('Could not activate the scene.'); }
      finally { card.classList.remove('sp-activating'); }
    }
  });
  ctx.on($('#sp-mix-save'), 'click', async () => {
    const msg = $('#sp-mix-msg');
    try {
      const r = await api.post('/api/smart-scenes/from-queue', { name: $('#sp-mix-name').value, campaign_id: $('#campaignDropdown').value, scene_ids: [...picked].map(x => parseInt(x, 10)) }, { quiet: true });
      if (!r.ok) { msg.textContent = r.error || 'Could not save.'; return; }
      msg.textContent = 'Saved "' + r.name + '" (' + r.added.music + ' songs, ' + r.added.video + ' videos).';
      ctx.after(900, () => ctx.reload());
    } catch (x) { msg.textContent = 'Could not save.'; }
  });

  // sort (remembered per browser)
  const sortScenes = (mode, remember) => {
    const cards = [...grid.querySelectorAll('.sp-scene-card')];
    cards.forEach((c, i) => { if (c.dataset.order === undefined) c.dataset.order = i; });
    const name = c => c.querySelector('.sp-scene-name').textContent.trim().toLowerCase();
    cards.sort((a, b) => mode === 'name' ? name(a).localeCompare(name(b), undefined, { numeric: true }) : parseInt(a.dataset.order, 10) - parseInt(b.dataset.order, 10));
    cards.forEach(c => grid.appendChild(c));
    $('#sceneSort').value = mode;
    if (remember) { try { localStorage.setItem('sp-scene-sort', mode); } catch (e) {} }
    $('#sceneDragHint').style.display = mode !== 'name' ? '' : 'none';
  };
  ctx.on($('#sceneSort'), 'change', e => sortScenes(e.target.value, true));
  try { sortScenes(localStorage.getItem('sp-scene-sort') || 'order', false); } catch (e) {}

  // drag & drop reorder (play order only)
  let dragging = null, dragged = false;
  const dragEnabled = () => $('#sceneSort').value !== 'name';
  ctx.on(grid, 'dragstart', e => {
    const card = e.target.closest && e.target.closest('.sp-scene-card');
    if (!card || !dragEnabled()) { if (card) e.preventDefault(); return; }
    dragging = card; dragged = false; card.classList.add('sp-dragging');
    e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', card.dataset.sceneId); } catch (x) {}
  });
  ctx.on(grid, 'dragover', e => {
    const over = e.target.closest && e.target.closest('.sp-scene-card');
    if (!dragging || !over || over === dragging) return;
    e.preventDefault(); dragged = true;
    const r = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragging, (e.clientX - r.left) < r.width / 2 ? over : over.nextSibling);
  });
  ctx.on(grid, 'dragend', async () => {
    if (!dragging) return;
    dragging.classList.remove('sp-dragging');
    const moved = dragged; dragging = null;
    if (!moved) return;
    const cards = [...grid.querySelectorAll('.sp-scene-card')];
    cards.forEach((c, i) => { c.dataset.order = i; });
    const hint = $('#sceneDragHint');
    try { const r = await api.post('/api/scenes/reorder', { scene_ids: cards.map(c => parseInt(c.dataset.sceneId, 10)) }, { quiet: true }); hint.textContent = r.ok ? 'order saved' : 'could not save order'; }
    catch (x) { hint.textContent = 'could not save order'; }
    ctx.after(2000, () => { hint.textContent = 'drag cards to reorder'; });
  });

  // queue states: SSE `queue` carries scene_states; fallback poll like before
  ctx.subscribe('queue', q => { if (q && q.scene_states) applyStates(q.scene_states); },
    { fallback: { every: 5000, fetch: () => api.get('/api/scenes/queue-states', { quiet: true }).then(r => ({ scene_states: r.states })) } });
  mixBar();
}

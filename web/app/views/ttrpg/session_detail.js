// Session page (DM) — templates/ttrpg/session_detail.html: party, notes
// (session + map), campaign scenes, monster tracker.
import { html, render, raw, esc } from '../../lib/dom.js';
import { api } from '../../api.js';
import { hpBar, avatar } from './_common.js';
import { toast } from '../../ui/toast.js';

export const title = ctx => 'Session';

export async function mount(outlet, ctx) {
  const SESSION_ID = ctx.params.id;
  const d = await api.get(`/api/v1/sessions/${SESSION_ID}/page`);
  const s = d.sess, g = d.game;
  document.title = `Session #${s.session_number}: ${s.title} — ScenePlay`;
  const alive = d.monsters.filter(m => m.is_alive).sort((a, b) => a.sort_order - b.sort_order), dead = d.monsters.filter(m => !m.is_alive);
  const partyIds = new Set(d.party_ids);
  render(outlet, html`
  <div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-2">
    <div><h3 style="color:var(--ttrpg-accent);" class="mb-0" id="sessHeading">Session #${s.session_number}: ${s.title}</h3>
      <span class="small text-muted" id="sessSubheading">${s.session_date || 'No date set'}${s.campaign_name ? html`&nbsp;&bull;&nbsp;<span id="sessCampaignName">${s.campaign_name}</span>` : html`<span id="sessCampaignName"></span>`}</span></div>
    <div class="d-flex gap-2 flex-wrap">
      <a href="/ttrpg/battlemap/session/${s.session_id}" class="btn btn-sm btn-ttrpg">&#9776; Battle Maps</a>
      ${d.active_map ? html`<a href="/ttrpg/battlemap/${d.active_map.map_id}/view" class="btn btn-ttrpg btn-sm">&#9776; Open Map</a>` : ''}
      ${s.status === 'planning' ? html`<button class="btn btn-success btn-sm" data-status="active">&#9654; Start Session</button>`
        : s.status === 'active' ? html`<button class="btn btn-warning btn-sm text-dark" data-status="ended">&#9632; End Session</button>`
        : html`<button class="btn btn-outline-secondary btn-sm" data-status="planning">&#8617; Reopen as Planning</button><button class="btn btn-success btn-sm" data-status="active">&#9654; Reactivate</button>`}
      <button class="btn btn-outline-secondary btn-sm" id="btn-edit" title="Edit session details">&#9998; Edit</button>
      <button class="btn btn-outline-danger btn-sm" id="btn-delete">Delete</button></div></div>
  <div id="sessEditPanel" class="ttrpg-card p-3 mb-3" style="display:none;"><div class="row g-2 align-items-end">
    <div class="col-sm-5"><label class="form-label small mb-1">Title</label><input type="text" id="editTitle" class="form-control form-control-sm" value="${s.title}"></div>
    <div class="col-sm-2"><label class="form-label small mb-1">Session #</label><input type="number" id="editNumber" class="form-control form-control-sm" value="${s.session_number}" min="1"></div>
    <div class="col-sm-2"><label class="form-label small mb-1">Date</label><input type="date" id="editDate" class="form-control form-control-sm" value="${s.session_date || ''}"></div>
    <div class="col-sm-3"><label class="form-label small mb-1">Campaign</label><select id="editCampaign" class="form-select form-select-sm"><option value="">— None —</option>${d.campaigns.map(c => html`<option value="${c.campaign_id}" ${s.campaign_id === c.campaign_id ? 'selected' : ''}>${c.campaign_name}</option>`)}</select></div>
    <div class="col-sm-4"><label class="form-label small mb-1">Game system</label><select id="editGameSystem" class="form-select form-select-sm">${Object.entries(d.game_systems).map(([sid, gs]) => html`<option value="${sid}" ${g.id === sid ? 'selected' : ''}>${gs.name}</option>`)}</select><div class="form-text">Which rules the dice rollers follow while this session is live.</div></div>
    <div class="col-sm-2" id="editFloorWrap" style="${g.id !== 'dcc' ? 'display:none;' : ''}"><label class="form-label small mb-1">Current Floor</label><input type="number" id="editFloor" class="form-control form-control-sm" value="${g.settings.floor || 3}" min="1" max="18"></div></div>
    <div class="mt-2 d-flex gap-2 justify-content-end"><span id="sessEditSaved" class="small text-success align-self-center" style="display:none;">Saved</span><button class="btn btn-outline-secondary btn-sm" id="btn-edit-cancel">Cancel</button><button class="btn btn-ttrpg btn-sm" id="btn-edit-save">Save</button></div></div>
  ${s.status === 'active' ? html`<div class="alert mb-3" style="background:var(--ttrpg-surface);border:1px solid #28a745;color:#1d7a34;">&#9654; Session is live</div>` : s.status === 'ended' ? html`<div class="alert mb-3" style="background:var(--ttrpg-surface);border:1px solid var(--sp-border);color:var(--sp-muted);">&#9632; Session ended — reopen to resume or access maps</div>` : ''}
  <style>@media (min-width: 768px) { .sess-split-party { flex: 0 0 35%; max-width: 35%; } .sess-split-notes { flex: 0 0 65%; max-width: 65%; } }</style>
  <div class="row g-3">
    <div class="col-md-6 sess-split-party"><div class="ttrpg-card p-3">
      <div class="d-flex justify-content-between align-items-center mb-2"><h5 style="color:var(--ttrpg-accent);">Party</h5><button class="btn btn-sm btn-outline-secondary" id="btn-add-party">+ Add</button></div>
      <div id="add-party-panel" class="mb-3" style="display:none;"><select id="add-char-select" class="form-select form-select-sm mb-2"><option value="">Select character…</option>${d.all_chars.filter(c => !partyIds.has(c.character_id)).map(c => html`<option value="${c.character_id}">${c.name} (${c.user_display_name})</option>`)}</select><button class="btn btn-ttrpg btn-sm" id="btn-add-party-go">Add to Party</button></div>
      ${d.party.length ? d.party.map(c => html`<div class="d-flex align-items-center gap-2 mb-2 ttrpg-card p-2" style="border-color:var(--sp-border);">${avatar(c, 36)}
        <div class="flex-grow-1" style="min-width:0;"><a href="/ttrpg/character/${c.character_id}" style="color:var(--ttrpg-accent);" class="text-truncate d-block fw-bold">${c.name}</a>
          <div class="small text-muted">${c.user_display_name} &bull; ${c.is_dcc ? `Health Bar ${c.hp_pct}%` : `HP ${c.hp_current}/${c.hp_max}`}</div>${hpBar(c, 5)}</div>
        <button class="btn btn-sm btn-outline-danger" data-remove-party="${c.character_id}">&#10005;</button></div>`) : html`<p class="text-muted small">No characters in this session yet.</p>`}</div></div>
    <div class="col-md-6 sess-split-notes"><div class="ttrpg-card p-3 h-100 d-flex flex-column">
      <div class="d-flex justify-content-between align-items-center mb-2"><div class="btn-group btn-group-sm"><button id="notes-tab-session" class="btn btn-sm btn-ttrpg">Session Notes</button><button id="notes-tab-maps" class="btn btn-sm btn-outline-secondary">Map Notes</button></div>
        <button class="btn btn-sm btn-outline-secondary" id="sess-note-new-btn">&#43; New Note</button></div>
      <div id="sess-notes-list" class="flex-column gap-1 flex-grow-1" style="display:flex;overflow-y:auto;max-height:380px;"><p class="text-muted small mb-0">Loading&#8230;</p></div>
      <div id="sess-note-editor" style="display:none;" class="flex-column flex-grow-1">
        <input id="sess-note-title" maxlength="120" placeholder="Title" class="form-control form-control-sm mb-2">
        <textarea id="sess-note-body" rows="9" placeholder="Write your note&#8230;" class="form-control flex-grow-1" style="resize:vertical;"></textarea>
        <div class="d-flex gap-2 align-items-center mt-2"><button class="btn btn-ttrpg btn-sm" id="note-save">Save</button><button class="btn btn-sm btn-outline-secondary" id="note-back" title="Back to the list (saves any changes)">&#8592; Back</button><span id="sess-note-ctx" class="small text-muted"></span><span id="sess-note-status" class="small text-success ms-auto"></span><button class="btn btn-sm btn-outline-danger" id="note-delete" title="Delete this note">&#128465;</button></div></div></div></div>
    <div class="col-12"><div class="ttrpg-card p-3">
      <div class="d-flex justify-content-between align-items-center mb-3"><h5 style="color:var(--ttrpg-accent);" class="mb-0">&#9836; Campaign Scenes</h5>${s.campaign_name ? html`<span class="small text-muted">${s.campaign_name}</span>` : ''}</div>
      ${d.campaign_scenes.length ? html`<div id="active-scene-banner" class="mb-2" style="display:none;"><span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);font-size:.85rem;">&#9654; <span id="active-scene-name"></span></span></div>
        <div class="d-flex flex-wrap gap-2">${d.campaign_scenes.map(sc => html`<button class="btn btn-sm scene-btn" data-scene-id="${sc.scene_ID}" data-scene-name="${sc.sceneName}" style="background:var(--ttrpg-surface);color:var(--ttrpg-text);border:1px solid var(--sp-border);">${sc.sceneName}${sc.obs_scene ? html`<span class="scene-obs-flag" style="font-size:.75rem;opacity:${d.obs_links_live ? 1 : 0.35};" title="${d.obs_links_live ? `Also cuts OBS to "${sc.obs_scene}"` : `Mapped to OBS "${sc.obs_scene}", but scene linking is switched OFF on the Broadcast page, so it will not cut`}"> &#127909;</span>` : ''}</button>`)}</div>`
        : s.campaign_id ? html`<p class="text-muted small mb-0">No active scenes found for this campaign.</p>` : html`<p class="text-muted small mb-0">Link this session to a campaign to see its scenes here.</p>`}
      <hr style="border-color:var(--sp-border);margin:12px 0 10px;">
      <div class="d-flex align-items-center gap-2 flex-wrap" style="min-width:0;"><span class="small text-muted" style="flex-shrink:0;">&#128266; PC Volume</span>
        <input type="range" id="pc-vol-slider" min="0" max="100" value="${d.current_vol}" style="flex:0 1 150px;min-width:60px;max-width:150px;accent-color:var(--ttrpg-accent);cursor:pointer;"><span id="pc-vol-label" style="font-size:.75rem;color:var(--sp-muted);min-width:26px;flex-shrink:0;text-align:right;">${d.current_vol}</span>
        <button type="button" class="btn btn-danger btn-sm py-0 px-2" id="btn-allstop" title="Stop all media &amp; clear the active scene">All Stop</button></div></div></div>
    <div class="col-12"><div class="ttrpg-card p-3">
      <div class="d-flex justify-content-between align-items-center mb-3"><h5 style="color:var(--ttrpg-accent);" class="mb-0">&#9876; Monsters &amp; Assets</h5><a href="/ttrpg/monsters" class="btn btn-sm btn-ttrpg">Monsters &amp; Assets Library</a></div>
      ${d.monsters.length ? html`${alive.length ? html`<div class="mb-3">${alive.map(m => html`<div class="ttrpg-card p-2 mb-2 monster-instance" id="mi-${m.monster_id}" style="border-color:var(--sp-border);">
        <div class="d-flex align-items-center gap-2 flex-wrap">
          ${m.image ? html`<img src="${m.image}" style="width:44px;height:44px;object-fit:contain;border-radius:4px;background:var(--ttrpg-primary);flex-shrink:0;" alt="">` : html`<div style="width:44px;height:44px;border-radius:4px;background:var(--ttrpg-primary);display:flex;align-items:center;justify-content:center;font-size:1.4rem;flex-shrink:0;">&#9876;</div>`}
          <div style="min-width:110px;flex:1;"><span class="fw-bold" style="color:var(--ttrpg-text);">${m.display_name}</span><div class="small text-muted">${m.size} ${m.type}</div></div>
          <div class="d-flex align-items-center gap-1"><button class="btn btn-sm btn-outline-danger px-2" data-mhp="${m.monster_id}" data-dir="-1" title="Apply damage">&#9660; Dmg</button>
            <input type="number" id="mi-amt-${m.monster_id}" value="1" min="1" class="form-control form-control-sm text-center" style="width:52px;">
            <button class="btn btn-sm btn-outline-success px-2" data-mhp="${m.monster_id}" data-dir="1" title="Apply healing">&#9650; Heal</button>
            <input type="number" id="mi-hp-${m.monster_id}" value="${m.hp_current}" min="0" max="${m.hp_max}" class="form-control form-control-sm text-center fw-bold" style="width:58px;color:var(--ttrpg-accent);" data-mhpset="${m.monster_id}" data-max="${m.hp_max}"><span class="small text-muted">/${m.hp_max}</span></div>
          <div class="flex-grow-1" style="min-width:60px;"><div class="progress" style="height:6px;background:var(--sp-border);"><div id="mi-bar-${m.monster_id}" class="progress-bar" style="width:${m.hp_pct}%;background:${m.hp_color};transition:width .3s;"></div></div></div>
          <div class="d-flex gap-1"><button class="btn btn-sm btn-outline-warning" data-mcond="${m.monster_id}" title="Conditions">&#9763;</button><button class="btn btn-sm btn-outline-danger" data-mkill="${m.monster_id}" title="Kill">&#9760;</button><button class="btn btn-sm btn-outline-secondary" data-mremove="${m.monster_id}" title="Remove">&#10005;</button></div></div>
        <div id="cond-display-${m.monster_id}" class="mt-1 d-flex flex-wrap gap-1">${m.conditions.map(c => html`<span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);">${c} <span style="cursor:pointer;" data-mcondrm="${m.monster_id}" data-cond="${c}">&#215;</span></span>`)}</div>
        <div id="cond-panel-${m.monster_id}" class="mt-2 d-flex flex-wrap gap-1" style="display:none!important;">${Object.keys(d.conditions).map(c => html`<button class="btn btn-sm btn-outline-secondary py-0" data-mcondadd="${m.monster_id}" data-cond="${c}">${c}</button>`)}</div></div>`)}</div>` : ''}
      ${dead.length ? html`<details class="ttrpg-card p-2" style="border-color:var(--sp-border);"><summary class="small text-muted" style="cursor:pointer;">&#9760; Defeated (${dead.length})</summary><div class="mt-2">${dead.map(m => html`<div class="d-flex align-items-center justify-content-between gap-2 py-1" style="border-top:1px solid var(--sp-border);"><span class="text-decoration-line-through" style="color:var(--sp-muted);">${m.display_name}</span><div class="d-flex gap-1"><button class="btn btn-sm btn-outline-secondary py-0" data-mrevive="${m.monster_id}">Revive</button><button class="btn btn-sm btn-outline-danger py-0" data-mremove="${m.monster_id}">&#10005;</button></div></div>`)}</div></details>` : ''}`
      : html`<p class="text-muted small">No monsters added yet. Use the <a href="/ttrpg/monsters" style="color:var(--ttrpg-accent);">Monsters &amp; Assets Library</a> to add monsters to this session.</p>`}</div></div>
  </div>`);

  const $ = s => outlet.querySelector(s);
  const post = (p, b) => api.post(p, b || null, { quiet: true });

  // status / delete / edit
  ctx.on(outlet, 'click', async e => {
    const st = e.target.closest('button[data-status]');
    if (st) { await post(`/ttrpg/sessions/${SESSION_ID}/status`, { status: st.dataset.status }); ctx.reload(); return; }
    const rp = e.target.closest('[data-remove-party]');
    if (rp) { if (!confirm('Remove from party?')) return; await post(`/ttrpg/sessions/${SESSION_ID}/party/${rp.dataset.removeParty}/remove`); ctx.reload(); return; }
  });
  ctx.on($('#btn-delete'), 'click', async () => { if (!confirm('Delete this session?')) return; const r = await post(`/ttrpg/sessions/${SESSION_ID}/delete`); toast.success(r.message); ctx.navigate('/ttrpg/sessions'); });
  const toggleEdit = () => { const p = $('#sessEditPanel'); p.style.display = p.style.display === 'none' ? '' : 'none'; };
  ctx.on($('#btn-edit'), 'click', toggleEdit); ctx.on($('#btn-edit-cancel'), 'click', toggleEdit);
  ctx.on($('#editGameSystem'), 'change', e => { $('#editFloorWrap').style.display = e.target.value === 'dcc' ? '' : 'none'; });
  ctx.on($('#btn-edit-save'), 'click', async () => {
    const r = await post(`/ttrpg/sessions/${SESSION_ID}/edit`, { title: $('#editTitle').value.trim(), session_number: $('#editNumber').value, session_date: $('#editDate').value, campaign_id: $('#editCampaign').value || null, game_system: $('#editGameSystem').value, floor: $('#editFloor').value });
    if (!r.ok) return;
    $('#sessHeading').textContent = `Session #${r.session_number}: ${r.title}`;
    const campEl = $('#sessCampaignName'), sub = $('#sessSubheading');
    let subText = r.session_date || 'No date set';
    if (r.campaign_name) { subText += ' • '; campEl.textContent = r.campaign_name; } else campEl.textContent = '';
    sub.childNodes[0].textContent = subText;
    const sv = $('#sessEditSaved'); sv.style.display = 'inline'; ctx.after(2000, () => { sv.style.display = 'none'; });
  });
  ctx.on($('#btn-add-party'), 'click', () => { const p = $('#add-party-panel'); p.style.display = p.style.display === 'none' ? 'block' : 'none'; });
  ctx.on($('#btn-add-party-go'), 'click', async () => { const id = $('#add-char-select').value; if (!id) return; await post(`/ttrpg/sessions/${SESSION_ID}/party/add`, { character_id: id }); ctx.reload(); });

  // ── notes (two tabs, one editor) ──
  let notesTabName = 'session', notes = [], mapGroups = [], mapOpenId = null, noteId = null, noteMapId = null, noteClean = '', noteGen = 0;
  const noteBase = () => noteMapId == null ? `/ttrpg/sessions/${SESSION_ID}/notes` : `/ttrpg/battlemap/${noteMapId}/notes`;
  const noteKey = () => $('#sess-note-title').value + '\n\n' + $('#sess-note-body').value;
  const showEditor = ctxLabel => { $('#sess-note-status').textContent = ''; $('#sess-note-ctx').textContent = ctxLabel || ''; $('#sess-notes-list').style.display = 'none'; $('#sess-note-editor').style.display = 'flex'; };
  const noteSave = () => {
    const t = $('#sess-note-title').value, b = $('#sess-note-body').value, status = $('#sess-note-status');
    if (noteId == null && !t.trim() && !b.trim()) return null;
    const url = noteId == null ? `${noteBase()}/add` : `${noteBase()}/${noteId}/update`; const gen = noteGen;
    return post(url, { title: t, body: b }).then(r => { if (gen !== noteGen) return; if (!r.ok) { status.textContent = 'Save failed'; return; } if (noteId == null && r.note_id) noteId = r.note_id; noteClean = noteKey(); status.textContent = 'Saved ✓'; ctx.after(2000, () => { if (status.textContent === 'Saved ✓') status.textContent = ''; }); })
      .catch(() => { if (gen === noteGen) status.textContent = 'Save failed'; });
  };
  const saveIfDirty = () => { const ed = $('#sess-note-editor'); if (!ed || ed.style.display === 'none') return null; return noteKey() !== noteClean ? noteSave() : null; };
  const showList = () => {
    const pending = saveIfDirty(); noteGen++; noteId = null; noteMapId = null;
    $('#sess-note-editor').style.display = 'none'; $('#sess-notes-list').style.display = 'flex';
    const url = notesTabName === 'maps' ? `/ttrpg/sessions/${SESSION_ID}/mapnotes/list` : `/ttrpg/sessions/${SESSION_ID}/notes/list`;
    Promise.resolve(pending).then(() => api.get(url, { quiet: true })).then(r => { if (!r.ok) return; if (notesTabName === 'maps') { mapGroups = r.maps; renderMapsTab(); } else { notes = r.notes; renderNotesList(); } }).catch(() => {});
  };
  const rowHtml = (n, i, len) => { const snip = (n.body || '').split('\n')[0].slice(0, 90); return `<div class="sess-note-row d-flex align-items-center gap-2 p-2" data-note-id="${n.note_id}" style="background:var(--ttrpg-surface);border:1px solid var(--sp-border);border-radius:6px;cursor:pointer;"><div style="flex:1;min-width:0;"><div style="font-weight:600;color:var(--ttrpg-accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(n.title || 'Untitled')}</div>${snip ? `<div class="text-muted small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(snip)}</div>` : ''}<div class="text-muted" style="font-size:.64rem;">${esc(n.updated_at || '')}</div></div><div class="d-flex flex-column" style="gap:2px;flex-shrink:0;"><button class="btn btn-sm py-0 px-1 btn-outline-secondary sn-move" data-dir="up" style="line-height:1;${i === 0 ? 'visibility:hidden;' : ''}" title="Move up">&#9650;</button><button class="btn btn-sm py-0 px-1 btn-outline-secondary sn-move" data-dir="down" style="line-height:1;${i === len - 1 ? 'visibility:hidden;' : ''}" title="Move down">&#9660;</button></div></div>`; };
  const renderNotesList = () => { const host = $('#sess-notes-list'); host.innerHTML = notes.length ? notes.map((n, i) => rowHtml(n, i, notes.length)).join('') : '<p class="text-muted small mb-0">No notes yet — use + New Note.</p>'; };
  const renderMapsTab = () => { const gr = mapOpenId != null && mapGroups.find(x => x.map_id === mapOpenId); if (gr) renderMapGroup(gr); else { mapOpenId = null; renderMapGrid(); } };
  const renderMapGrid = () => { const host = $('#sess-notes-list'); host.innerHTML = mapGroups.length ? mapGroups.map(gr => `<div class="sess-map-row d-flex align-items-center gap-2 p-2" data-map-id="${gr.map_id}" style="background:var(--ttrpg-surface);border:1px solid var(--sp-border);border-radius:6px;cursor:pointer;"><div style="flex:1;min-width:0;font-weight:600;color:var(--ttrpg-accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">&#128506; ${esc(gr.name)}</div><span class="badge bg-secondary" title="${gr.notes.length} note(s) on this map">${gr.notes.length}</span></div>`).join('') : '<p class="text-muted small mb-0">No battle maps in this session yet.</p>'; };
  const renderMapGroup = gr => { const host = $('#sess-notes-list'); host.innerHTML = `<div class="d-flex align-items-center gap-2 mb-1"><button class="btn btn-sm py-0 btn-outline-secondary" id="sn-maps-back" title="Back to the maps list">&#8592; Maps</button><div class="small flex-grow-1" style="color:var(--ttrpg-accent);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">&#128506; ${esc(gr.name)}</div><button class="btn btn-sm py-0 btn-outline-secondary" id="sn-map-add" title="Add a note to this map">&#43; Add</button></div>` + (gr.notes.map((n, i) => rowHtml(n, i, gr.notes.length).replace('</div></div>', `</div><button class="btn btn-sm py-0 px-1 btn-outline-danger sn-del" title="Delete note" style="flex-shrink:0;">&#128465;</button></div>`)).join('') || '<p class="text-muted small mb-0">No notes for this map yet.</p>'); };
  const noteOpen = (id, mapId = null) => {
    let n, label = '';
    if (mapId != null) { const gr = mapGroups.find(x => x.map_id === mapId); n = gr && gr.notes.find(x => x.note_id === id); label = gr ? `Map: ${gr.name}` : ''; } else n = notes.find(x => x.note_id === id);
    if (!n) return; noteGen++; noteId = id; noteMapId = mapId; $('#sess-note-title').value = n.title || ''; $('#sess-note-body').value = n.body || ''; noteClean = noteKey(); showEditor(label); $('#sess-note-body').focus();
  };
  const noteNew = (mapId = null, mapName = '') => { noteGen++; noteId = null; noteMapId = mapId; $('#sess-note-title').value = ''; $('#sess-note-body').value = ''; noteClean = noteKey(); showEditor(mapId != null ? `Map: ${mapName}` : ''); $('#sess-note-title').focus(); };
  const setTab = t => { notesTabName = t; mapOpenId = null; const bS = $('#notes-tab-session'), bM = $('#notes-tab-maps'); bS.classList.toggle('btn-ttrpg', t === 'session'); bS.classList.toggle('btn-outline-secondary', t !== 'session'); bM.classList.toggle('btn-ttrpg', t === 'maps'); bM.classList.toggle('btn-outline-secondary', t !== 'maps'); $('#sess-note-new-btn').style.display = t === 'session' ? '' : 'none'; showList(); };
  ctx.on($('#notes-tab-session'), 'click', () => setTab('session')); ctx.on($('#notes-tab-maps'), 'click', () => setTab('maps'));
  ctx.on($('#sess-note-new-btn'), 'click', () => noteNew()); ctx.on($('#note-save'), 'click', noteSave); ctx.on($('#note-back'), 'click', showList);
  ctx.on($('#note-delete'), 'click', async () => { if (noteId == null) { noteClean = noteKey(); showList(); return; } if (!confirm('Delete this note?')) return; const id = noteId, base = noteBase(); noteId = null; noteClean = noteKey(); await post(`${base}/${id}/delete`); showList(); });
  ctx.on($('#sess-notes-list'), 'click', async e => {
    const mv = e.target.closest('.sn-move'), del = e.target.closest('.sn-del'), row = e.target.closest('.sess-note-row'), mrow = e.target.closest('.sess-map-row');
    if (e.target.closest('#sn-maps-back')) { mapOpenId = null; renderMapsTab(); return; }
    if (e.target.closest('#sn-map-add')) { const gr = mapGroups.find(x => x.map_id === mapOpenId); if (gr) noteNew(gr.map_id, gr.name); return; }
    if (mv && row) { e.stopPropagation(); const base = notesTabName === 'maps' ? `/ttrpg/battlemap/${mapOpenId}/notes` : `/ttrpg/sessions/${SESSION_ID}/notes`; const r = await post(`${base}/${row.dataset.noteId}/reorder`, { direction: mv.dataset.dir }); if (r.ok) showList(); return; }
    if (del && row) { e.stopPropagation(); if (!confirm('Delete this note?')) return; await post(`/ttrpg/battlemap/${mapOpenId}/notes/${row.dataset.noteId}/delete`); showList(); return; }
    if (row) { noteOpen(parseInt(row.dataset.noteId), notesTabName === 'maps' ? mapOpenId : null); return; }
    if (mrow) { mapOpenId = parseInt(mrow.dataset.mapId); renderMapsTab(); }
  });
  ctx.on(window, 'beforeunload', saveIfDirty); ctx.every(30000, saveIfDirty); ctx.cleanup(() => { saveIfDirty(); });
  showList();

  // ── scenes / volume / all stop ──
  ctx.on(outlet, 'click', async e => {
    const sb = e.target.closest('.scene-btn');
    if (sb) { await post('/activatescenes/?id=' + sb.dataset.sceneId); outlet.querySelectorAll('.scene-btn').forEach(b => { b.style.borderColor = 'var(--sp-border)'; b.style.color = 'var(--ttrpg-text)'; }); sb.style.borderColor = 'var(--ttrpg-accent)'; sb.style.color = 'var(--ttrpg-accent)'; $('#active-scene-name').textContent = sb.dataset.sceneName; $('#active-scene-banner').style.display = ''; }
  });
  ctx.on($('#btn-allstop'), 'click', async () => { try { await post('/killqueue'); } catch (x) {} post('/activatescenes/?id=-1').catch(() => {}); outlet.querySelectorAll('.scene-btn').forEach(b => { b.style.borderColor = 'var(--sp-border)'; b.style.color = 'var(--ttrpg-text)'; }); const banner = $('#active-scene-banner'); if (banner) banner.style.display = 'none'; });
  let volT = null; ctx.on($('#pc-vol-slider'), 'input', e => { $('#pc-vol-label').textContent = e.target.value; clearTimeout(volT); volT = setTimeout(() => post('/set_volume', { volume: parseInt(e.target.value) }).catch(() => {}), 120); });

  // ── monster tracker ──
  const paintHp = (id, data) => { const inp = $(`#mi-hp-${id}`); if (inp) inp.value = data.hp_current; const bar = $(`#mi-bar-${id}`); if (bar) { bar.style.width = data.hp_pct + '%'; bar.style.background = data.hp_pct > 50 ? '#28a745' : data.hp_pct > 20 ? '#ffc107' : '#dc3545'; } if (!data.is_alive) ctx.reload(); };
  ctx.on(outlet, 'click', async e => {
    const hp = e.target.closest('[data-mhp]'); if (hp) { const id = hp.dataset.mhp, amt = parseInt($(`#mi-amt-${id}`).value) || 1; const r = await post(`/ttrpg/monsters/instance/${id}/hp`, { delta: Number(hp.dataset.dir) * amt }); if (r.ok) paintHp(id, r); return; }
    const kill = e.target.closest('[data-mkill]'); if (kill) { if (!confirm('Mark this monster as dead?')) return; await post(`/ttrpg/monsters/instance/${kill.dataset.mkill}/hp`, { delta: -9999 }); ctx.reload(); return; }
    const rev = e.target.closest('[data-mrevive]'); if (rev) { await post(`/ttrpg/monsters/instance/${rev.dataset.mrevive}/revive`); ctx.reload(); return; }
    const rm = e.target.closest('[data-mremove]'); if (rm) { if (!confirm('Remove this monster from the session?')) return; await post(`/ttrpg/monsters/instance/${rm.dataset.mremove}/delete`); ctx.reload(); return; }
    const cp = e.target.closest('[data-mcond]'); if (cp) { const el = $(`#cond-panel-${cp.dataset.mcond}`); el.style.setProperty('display', el.style.display === 'none' ? 'flex' : 'none', 'important'); return; }
    const ca = e.target.closest('[data-mcondadd]'); if (ca) { await post(`/ttrpg/monsters/instance/${ca.dataset.mcondadd}/condition`, { condition: ca.dataset.cond, action: 'add' }); ctx.reload(); return; }
    const cr = e.target.closest('[data-mcondrm]'); if (cr) { await post(`/ttrpg/monsters/instance/${cr.dataset.mcondrm}/condition`, { condition: cr.dataset.cond, action: 'remove' }); ctx.reload(); return; }
  });
  ctx.on(outlet, 'change', async e => { const t = e.target.closest('[data-mhpset]'); if (!t) return; const clamped = Math.max(0, Math.min(Number(t.dataset.max), parseInt(t.value) || 0)); const r = await post(`/ttrpg/monsters/instance/${t.dataset.mhpset}/hp-set`, { hp: clamped }); if (r.ok) paintHp(t.dataset.mhpset, r); });
}

// Create character (templates/ttrpg/character_new.html) incl. randomizer,
// portrait paste/preview and the image-prompt modal.
import { html, render } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import { loadScripts } from '../../lib/loader.js';
import { toast } from '../../ui/toast.js';
import { suggestBox, dccBlock, bindLibSearch, applyGameSystem, bindTouched, fileFromBlob } from './_char_form.js';

export const title = 'Create Character';

export async function mount(outlet, ctx) {
  const [d] = await Promise.all([api.get('/api/v1/characters/new-options'), loadScripts(['/legacy/ai_generate.js', '/legacy/portrait_prompt.js', '/legacy/asset_picker.js'])]);
  const GENRE = d.genre_client_data;
  const num = (label, name, val, col = 'col-4 col-sm-2', extra = '') => html`<div class="${col}"><label class="form-label">${label}</label><input type="number" name="${name}" value="${val}" class="form-control" ${extra}></div>`;
  render(outlet, html`<div class="row justify-content-center"><div class="col-md-10 col-lg-8"><div class="ttrpg-card p-4">
    <div class="d-flex align-items-center gap-3 mb-1 flex-wrap">
      <h3 style="color:var(--ttrpg-accent);margin:0;">Create Character</h3>
      <button type="button" id="btn-randomize" class="btn btn-sm" style="background:var(--ttrpg-surface);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);font-size:.8rem;"><span class="dice-ico">&#127922;</span> Randomize</button>
      <div class="d-flex align-items-center gap-1"><span class="text-muted" style="font-size:.75rem;">Level</span>
        <select id="rand-dcc-floor" class="form-select form-select-sm" style="display:none;width:auto;" title="Where the crawler starts"><option value="third" selected>Third Floor crawler — Level 10 with Race and Class (the usual start)</option><option value="first">First Floor crawler — Level 1, Human, no Class yet (by the book)</option></select>
        <input type="number" id="rand-min-level" value="1" min="1" max="20" class="form-control form-control-sm text-center" style="width:58px;" title="Minimum random level"><span class="text-muted rand-dash">&ndash;</span>
        <input type="number" id="rand-max-level" value="20" min="1" max="20" class="form-control form-control-sm text-center" style="width:58px;" title="Maximum random level"></div>
      <select id="rand-genre" class="form-select form-select-sm" style="width:auto;" title="Genre skin for names, traits, and portrait style">${d.genre_options.map(([k, l]) => html`<option value="${k}">${l}</option>`)}</select></div>
    <div class="alert alert-danger" id="cn-error" style="display:none"></div>
    <form id="cn-form" enctype="multipart/form-data">
      <input type="hidden" name="genre" id="form-genre" value="fantasy"><input type="hidden" name="dcc_skills_json" id="dcc-skills-json" value=""><input type="hidden" name="dcc_items_json" id="dcc-items-json" value=""><input type="hidden" name="dcc_applied_json" id="dcc-applied-json" value="">
      <h6 class="text-muted mt-3 mb-2 text-uppercase" style="letter-spacing:.08em;">Game system</h6>
      <div class="row g-3"><div class="col-sm-6"><select name="game_system" id="gameSystemSel" class="form-select">${Object.entries(d.game_systems).map(([sid, gs]) => html`<option value="${sid}" ${d.game.id === sid ? 'selected' : ''}>${gs.name}</option>`)}</select><div class="form-text">Which rules this sheet is laid out for. Pre-set from the live session.</div></div></div>
      <h6 class="text-muted mt-3 mb-2 text-uppercase" style="letter-spacing:.08em;">Identity</h6>
      <div class="row g-3">
        <div class="col-sm-6"><label class="form-label">Character Name *</label><input type="text" name="name" class="form-control" required autofocus></div>
        <div class="col-sm-3"><label class="form-label">Class</label><div style="position:relative;"><input type="text" name="char_class" id="new-char-class" class="form-control" placeholder="Fighter, Wizard…" autocomplete="off">${suggestBox('new-class-suggestions')}</div></div>
        <div class="col-sm-3"><label class="form-label">Race</label><div style="position:relative;"><input type="text" name="race" id="new-race" class="form-control" placeholder="Human, Elf…" autocomplete="off">${suggestBox('new-race-suggestions')}</div></div>
        <div class="col-sm-3"><label class="form-label">Level</label><input type="number" name="level" class="form-control" value="1" min="1" max="30"></div>
        <div class="only-5e col-sm-3"><label class="form-label">Subclass</label><input type="text" name="subclass" class="form-control" placeholder="Champion… (level 3+)"></div>
        <div class="col-sm-6"><label class="form-label">Background</label><input type="text" name="background" class="form-control" placeholder="Soldier, Noble…"></div>
        <div class="col-sm-3"><label class="form-label">Portrait</label>
          <input type="file" name="portrait" id="new-portrait-input" class="form-control" accept="image/png,image/jpeg,image/gif,image/webp">
          <input type="hidden" name="portrait_ref" id="new-portrait-ref">
          <button type="button" class="btn btn-sm btn-outline-secondary mt-1" id="btn-pick" title="Reuse a picture already on this server — nothing is copied">&#128444; Choose existing</button>
          <div id="new-portrait-ref-preview" class="mt-1" style="display:none;"></div>
          <div id="new-portrait-preview" style="display:none;margin-top:4px;"><img id="new-portrait-img" src="" alt="" style="width:88px;height:88px;object-fit:cover;border-radius:6px;border:2px solid var(--ttrpg-accent);"></div>
          <button type="button" id="new-paste-btn" class="btn btn-sm btn-outline-secondary w-100 mt-1" style="font-size:.7rem;">&#128203; Paste Portrait</button>
          <button type="button" id="btn-prompt" class="btn btn-sm btn-outline-secondary w-100 mt-1" style="font-size:.7rem;">&#127748; Image Prompt</button></div>
        ${d.open_sessions.length ? html`<div class="col-sm-3"><label class="form-label">Add to Session</label><select name="add_session_id" class="form-select"><option value="">&mdash; none &mdash;</option>${d.open_sessions.map(s => html`<option value="${s.session_id}">${s.title}${s.status === 'active' ? ' (active)' : ''}</option>`)}</select><div class="form-text text-muted">Joins the party on create.</div></div>` : ''}
      </div>
      <div class="only-5e"><h6 class="text-muted mt-4 mb-2 text-uppercase" style="letter-spacing:.08em;">Combat Stats</h6>
        <div class="row g-3">${num('HP Max', 'hp_max', 0, 'col-4 col-sm-2', 'min="0"')}${num('AC', 'ac', 10, 'col-4 col-sm-2', 'min="0"')}${num('Speed', 'speed', 30, 'col-4 col-sm-2', 'min="0"')}${num('Initiative Bonus', 'initiative_bonus', 0, 'col-4 col-sm-3')}${num('Passive Perc.', 'passive_perception', 10, 'col-4 col-sm-3')}</div></div>
      <h6 class="text-muted mt-4 mb-2 text-uppercase" style="letter-spacing:.08em;">Attributes</h6>
      <div class="row g-3">${[['STR', 'str_val'], ['DEX', 'dex_val'], ['CON', 'con_val'], ['INT', 'int_val'], ['WIS', 'wis_val'], ['CHA', 'cha_val']].map(([l, f]) => html`<div class="col-4 col-sm-2${f === 'wis_val' ? ' only-5e' : ''}"><label class="form-label">${l}</label><input type="number" name="${f}" class="form-control text-center" value="10" min="1" max="30"></div>`)}</div>
      <h6 class="text-muted mt-4 mb-2 text-uppercase" style="letter-spacing:.08em;">Personality &amp; Traits</h6>
      <textarea name="traits_note" id="traits-note" rows="4" class="form-control" placeholder="Personality, ideal, bond, flaw — filled by Randomize, or write your own. Saved as the character's first note."></textarea>
      <h6 class="text-muted mt-4 mb-2 text-uppercase" style="letter-spacing:.08em;">Currency</h6>
      <div class="row g-3">${num('Gold', 'gold', 0, 'col-4 col-sm-2', 'min="0"')}${num('Silver', 'silver', 0, 'col-4 col-sm-2 only-5e', 'min="0"')}${num('Copper', 'copper', 0, 'col-4 col-sm-2 only-5e', 'min="0"')}</div>
      ${dccBlock(d.dcc, d.dcc_sizes, true)}
      <div class="mt-4 d-flex gap-2"><button type="submit" class="btn btn-ttrpg">Create Character</button><a href="/ttrpg/my-character" class="btn btn-outline-secondary">Cancel</a></div>
    </form></div></div></div>
  <div class="modal fade" id="newCharPromptModal" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content" style="background:var(--ttrpg-primary);border:1px solid var(--ttrpg-accent);color:var(--ttrpg-text);">
    <div class="modal-header" style="border-color:var(--ttrpg-accent);"><h5 class="modal-title" style="color:var(--ttrpg-accent);">&#127748; Image Prompt</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body"><p class="small text-muted mb-2">Copy this prompt and paste it into an image generation tool (Midjourney, DALL-E, Stable Diffusion) or ask Claude to generate the portrait.</p>
      <div class="d-flex align-items-center gap-2 mb-2"><button id="new-char-ai-btn" class="btn btn-sm btn-ttrpg ms-auto" style="display:none;font-size:.75rem;" title="One click: Gemini generates the portrait and attaches it to the form — it saves when you create the character">&#10024; Generate with Gemini</button>
        <button id="btn-copy-prompt" class="btn btn-sm" style="background:var(--ttrpg-surface);color:var(--ttrpg-accent);border:1px solid var(--ttrpg-accent);font-size:.75rem;">&#128203; Copy</button></div>
      <div id="new-char-ai-status" class="small mb-2"></div>
      <textarea id="new-char-prompt-text" class="form-control" style="font-family:monospace;font-size:.78rem;min-height:360px;background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);resize:vertical;" readonly></textarea></div>
    <div class="modal-footer" style="border-color:var(--ttrpg-accent);"><span id="new-char-copy-feedback" style="font-size:.8rem;color:var(--ttrpg-accent);display:none;">Copied!</span><button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Close</button></div></div></div></div>`);

  const $ = s => outlet.querySelector(s);
  const currentGenre = () => $('#rand-genre').value || 'fantasy';
  const syncGenre = () => { $('#form-genre').value = currentGenre(); };
  ctx.on($('#rand-genre'), 'change', syncGenre);
  bindLibSearch(ctx, outlet, { inputs: { class: 'new-char-class', race: 'new-race' }, boxes: { class: 'new-class-suggestions', race: 'new-race-suggestions' }, systemSel: 'gameSystemSel' });
  bindTouched(ctx, outlet);
  const sel = $('#gameSystemSel');
  const applySys = () => applyGameSystem(outlet, sel, dcc => {
    ['#rand-min-level', '#rand-max-level', '.rand-dash', '#rand-genre'].forEach(s => { const el = $(s); if (el) el.style.display = dcc ? 'none' : ''; });
    $('#rand-dcc-floor').style.display = dcc ? '' : 'none';
    if (!dcc) ['#dcc-skills-json', '#dcc-items-json', '#dcc-applied-json'].forEach(s => { $(s).value = ''; });
  });
  applySys(); ctx.on(sel, 'change', applySys);

  // portrait preview / paste / pick
  const showPreview = src => { $('#new-portrait-img').src = src; $('#new-portrait-preview').style.display = ''; };
  ctx.on($('#new-portrait-input'), 'change', e => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = ev => showPreview(ev.target.result); r.readAsDataURL(f); });
  const applyBlob = blob => { fileFromBlob(blob, $('#new-portrait-input')); const r = new FileReader(); r.onload = ev => showPreview(ev.target.result); r.readAsDataURL(blob); };
  ctx.on($('#btn-pick'), 'click', () => window.spPickAsset({ kinds: ['image'], onPick: it => { $('#new-portrait-ref').value = window.spAssetRef(it, 'portraits'); $('#new-portrait-input').value = ''; window.spAssetPreview($('#new-portrait-ref-preview'), it); } }));
  ctx.on($('#new-paste-btn'), 'click', async () => {
    const btn = $('#new-paste-btn'); btn.disabled = true; btn.textContent = 'Reading clipboard…';
    if (navigator.clipboard && navigator.clipboard.read) {
      try {
        for (const item of await navigator.clipboard.read()) { const t = item.types.find(x => x.startsWith('image/')); if (t) { applyBlob(await item.getType(t)); btn.innerHTML = '&#128203; Paste Portrait'; btn.disabled = false; return; } }
        btn.textContent = 'No image in clipboard'; ctx.after(2000, () => { btn.innerHTML = '&#128203; Paste Portrait'; btn.disabled = false; }); return;
      } catch (err) { /* fall through */ }
    }
    btn.textContent = 'Now paste (Ctrl+V)…'; btn.disabled = false; btn.style.borderColor = 'var(--ttrpg-accent)'; btn.style.color = 'var(--ttrpg-accent)';
    const reset = () => { btn.innerHTML = '&#128203; Paste Portrait'; btn.style.borderColor = ''; btn.style.color = ''; };
    const tid = setTimeout(reset, 15000);
    document.addEventListener('paste', function handler(e) { clearTimeout(tid); reset(); const it = Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/')); if (it) { e.preventDefault(); applyBlob(it.getAsFile()); } }, { once: true });
  });

  // randomizer
  ctx.on($('#btn-randomize'), 'click', async () => {
    const btn = $('#btn-randomize'); btn.disabled = true; btn.textContent = 'Rolling…';
    const set = (s, v) => { const el = outlet.querySelector(s); if (el) el.value = v; };
    try {
      if (sel.value === 'dcc') {
        const floor = $('#rand-dcc-floor').value || 'first';
        const c = await api.get('/ttrpg/character/random?system=dcc&floor=' + floor);
        set('[name="name"]', c.name); set('[name="level"]', c.level); set('[name="background"]', c.background);
        $('#new-char-class').value = c.char_class || ''; $('#new-race').value = c.race || '';
        ['str_val', 'int_val', 'con_val', 'dex_val', 'cha_val', 'gold'].forEach(f => set('[name="' + f + '"]', c[f]));
        outlet.querySelectorAll('input[name$="_val"]').forEach(inp => { inp.dataset.touched = '1'; });
        ['dcc_move', 'dcc_step', 'dcc_size', 'dcc_popularity', 'dcc_ai_favor', 'dcc_dr', 'dcc_crawler_number', 'dcc_past_trauma', 'dcc_loose_ends', 'dcc_regrets', 'dcc_floor_entered', 'dcc_stat_points'].forEach(f => set('[name="' + f + '"]', c[f]));
        $('#dcc-skills-json').value = JSON.stringify(c.skills || []); $('#dcc-items-json').value = JSON.stringify(c.items || []); $('#dcc-applied-json').value = JSON.stringify(c.applied || []);
        $('#traits-note').value = c.traits_note || '';
      } else {
        const lo = parseInt($('#rand-min-level').value) || 1, hi = parseInt($('#rand-max-level').value) || 20;
        const c = await api.get('/ttrpg/character/random?min_level=' + Math.min(lo, hi) + '&max_level=' + Math.max(lo, hi) + '&genre=' + encodeURIComponent(currentGenre()));
        syncGenre();
        set('[name="name"]', c.name); set('[name="level"]', c.level); set('[name="subclass"]', c.subclass || ''); set('[name="background"]', c.background);
        $('#new-char-class').value = c.char_class; $('#new-race').value = c.race;
        ['str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val', 'hp_max', 'ac', 'speed', 'initiative_bonus', 'passive_perception', 'gold', 'silver', 'copper'].forEach(f => set('[name="' + f + '"]', c[f]));
        $('#traits-note').value = c.traits_note || '';
      }
    } catch (err) { console.error('Randomize failed:', err); }
    btn.disabled = false; btn.innerHTML = '<span class="dice-ico">&#127922;</span> Randomize';
  });

  // image prompt modal
  const buildPrompt = () => {
    const fv = n => (outlet.querySelector('[name="' + n + '"]') || {}).value || ''; const fi = n => parseInt(fv(n)) || 0;
    const name = fv('name').trim() || 'the character', charClass = $('#new-char-class').value.trim(), subclass = fv('subclass').trim(), race = $('#new-race').value.trim(), background = fv('background').trim(), traitsNote = fv('traits_note').trim(), level = fi('level') || 1;
    const lines = ['Please generate a close-up portrait of the following fantasy TTRPG character.\n'];
    const pack = GENRE[currentGenre()];
    const dispRace = pack ? (pack.race_skins[race] || race) : race, dispClass = pack ? (pack.class_skins[charClass] || charClass) : charClass;
    const identity = [];
    if (race) identity.push(dispRace);
    if (charClass) identity.push((!pack && subclass ? subclass + ' ' : '') + dispClass + ' (Level ' + level + ')');
    if (background) identity.push(background + ' background');
    lines.push('CHARACTER: ' + name + (identity.length ? ', a ' + identity.join(', ') : '') + '.');
    if (pack) lines.push('SETTING: ' + pack.label + ' — not medieval fantasy.');
    lines.push('');
    if (traitsNote) { lines.push('PERSONALITY (let this shape expression, bearing, and mood):'); traitsNote.split('\n').forEach(l => { if (l.trim()) lines.push('- ' + l.trim()); }); lines.push(''); }
    const presence = window.portraitPresenceLines({ str: fi('str_val'), dex: fi('dex_val'), con: fi('con_val'), int: fi('int_val'), wis: fi('wis_val'), cha: fi('cha_val') });
    if (presence.length) { lines.push('PHYSICAL PRESENCE:'); presence.forEach(l => lines.push(l)); lines.push(''); }
    window.portraitStyleLines(false, pack ? pack.art_style : null).forEach(l => lines.push(l)); lines.push('');
    lines.push('Generate a vivid, detailed close-up portrait that captures the face, personality, and essence of ' + name + '.');
    return lines.join('\n');
  };
  const BS = window.bootstrap;
  ctx.on($('#btn-prompt'), 'click', () => { $('#new-char-prompt-text').value = buildPrompt(); BS.Modal.getOrCreateInstance($('#newCharPromptModal')).show(); });
  ctx.on($('#btn-copy-prompt'), 'click', () => { const ta = $('#new-char-prompt-text'), fb = $('#new-char-copy-feedback'); const showFb = () => { fb.style.display = ''; ctx.after(2000, () => { fb.style.display = 'none'; }); }; if (navigator.clipboard) navigator.clipboard.writeText(ta.value).then(showFb).catch(() => { ta.removeAttribute('readonly'); ta.select(); try { document.execCommand('copy'); showFb(); } catch (e) {} ta.setAttribute('readonly', ''); }); });
  ctx.on($('#new-char-ai-btn'), 'click', e => {
    const btn = e.currentTarget, status = $('#new-char-ai-status'), prompt = $('#new-char-prompt-text').value, input = $('#new-portrait-input');
    if (!prompt.trim() || !input) return;
    const orig = btn.innerHTML; btn.disabled = true; btn.textContent = '✨ Painting…'; status.textContent = ''; status.style.color = '';
    window.aiImageWithPreview(() => window.aiImageBlob(prompt), { title: 'Portrait preview', useLabel: 'Use as portrait', onRegenerate: () => { status.textContent = '✨ Painting another…'; } })
      .then(blob => { if (!blob) { status.textContent = 'Discarded — nothing attached.'; return; } window.aiBlobToFileInput(blob, input, 'portrait'); status.textContent = '✨ Portrait attached — it saves when you create the character.'; })
      .catch(x => { status.textContent = 'AI: ' + x.message; status.style.color = 'var(--bs-danger, #dc3545)'; })
      .finally(() => { btn.disabled = false; btn.innerHTML = orig; });
  });
  if (window.aiConfigured) window.aiConfigured().then(on => { const b = $('#new-char-ai-btn'); if (b && on) { b.style.display = ''; window.aiBrandImageButton(b); } }).catch(() => {});
  ctx.cleanup(() => { const m = $('#newCharPromptModal'); const inst = m && BS.Modal.getInstance(m); if (inst) inst.dispose(); document.querySelectorAll('.modal-backdrop').forEach(b => b.remove()); document.body.classList.remove('modal-open'); });

  ctx.on($('#cn-form'), 'submit', async e => {
    e.preventDefault(); const err = $('#cn-error'); err.style.display = 'none'; syncGenre();
    try { const r = await api.upload('/api/v1/characters', new FormData(e.target), { quiet: true }); if (r.message) toast.success(r.message); ctx.navigate('/ttrpg/character/' + r.character_id); }
    catch (x) { err.textContent = x instanceof ApiError ? x.message : String(x.message || x); err.style.display = ''; }
  });
}

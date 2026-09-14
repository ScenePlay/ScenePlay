// Character sheet view: page data -> template.render -> verbatim sheet.js.
import { render } from '../../../lib/dom.js';
import { api, ApiError } from '../../../api.js';
import { loadScripts, loadScript } from '../../../lib/loader.js';
import { toast } from '../../../ui/toast.js';
import { render as tpl, globals } from './template.js';
import { init } from './sheet.js';

export const title = 'Character';
let _mounts = 0;
const SFX_CTRL = '/legacy/sfx-control.js';

export async function mount(outlet, ctx) {
  const id = ctx.params.id;
  let d;
  try { d = await api.get(`/api/v1/characters/${id}/page`, { quiet: true }); }
  catch (e) { if (e instanceof ApiError && e.status === 403) { toast.error(e.message); return ctx.navigate('/ttrpg/my-character', { replace: true }); } throw e; }
  await loadScripts(['/shared/Tone.js', '/shared/dice.js', '/shared/sfx.js', '/legacy/ai_generate.js', '/legacy/portrait_prompt.js', '/legacy/asset_picker.js']);
  document.title = `${d.char.name} — ScenePlay`;
  render(outlet, tpl(d));
  const BS = window.bootstrap;
  const tips = Array.from(outlet.querySelectorAll('[data-bs-toggle="tooltip"]')).map(el => BS.Tooltip.getOrCreateInstance(el));
  const dispose = init(ctx, d, globals(d));
  ctx.cleanup(() => { dispose(); tips.forEach(t => { try { t.dispose(); } catch (e) {} }); document.querySelectorAll('.popover, .tooltip, .modal-backdrop').forEach(el => el.remove()); document.body.classList.remove('modal-open'); const m = outlet.querySelector('#llmPromptModal'); const inst = m && BS.Modal.getInstance(m); if (inst) inst.dispose(); });
  // sfx-control.js is a self-wiring IIFE; a fresh query string makes it run again per mount
  loadScript(SFX_CTRL + '?m=' + (++_mounts)).catch(() => {});

  const $ = s => outlet.querySelector(s);
  ctx.on(outlet, 'click', e => {
    const a = e.target.closest('a.more-toggle'); if (!a) return;
    e.preventDefault(); const open = a.dataset.open === '1';
    outlet.querySelectorAll(a.dataset.target).forEach(el => { el.style.display = open ? 'none' : ''; });
    a.dataset.open = open ? '0' : '1'; a.innerHTML = open ? '&#9660; +' + a.dataset.more + ' more' : '&#9650; less';
  });
  const postPortrait = async fd => { await api.upload(`/ttrpg/character/${id}/portrait`, fd); window.reloadKeepTab(); };
  const pin = $('#portraitInput');
  if (pin) ctx.on(pin, 'change', () => { if (pin.files[0]) { const fd = new FormData(); fd.append('portrait', pin.files[0]); postPortrait(fd); } });
  const reuse = $('#reuse-portrait-btn');
  if (reuse) ctx.on(reuse, 'click', () => window.spPickAsset({ kinds: ['image'], onPick: it => { const fd = new FormData(); fd.append('portrait_ref', window.spAssetRef(it, 'portraits')); postPortrait(fd); } }));
  const assign = $('#assign-form');
  if (assign) ctx.on(assign, 'submit', async e => { e.preventDefault(); const r = await api.post(`/ttrpg/character/${id}/assign`, { user_id: assign.user_id.value }); if (r.message) toast.success(r.message); window.reloadKeepTab(); });
  const rm = $('#remove-form');
  if (rm) ctx.on(rm, 'submit', async e => { e.preventDefault(); if (!confirm(`Remove ${d.char.name}?`)) return; const r = await api.post(`/ttrpg/character/${id}/delete`); if (r.message) toast.success(r.message); ctx.navigate('/ttrpg/characters'); });
  const gs = $('#game-system-sel');
  if (gs) ctx.on(gs, 'change', () => { if (confirm('Switch this sheet to ' + gs.options[gs.selectedIndex].text + '?')) window.saveField('game_system', gs.value, () => ctx.reload()); else gs.value = gs.dataset.current; });
}

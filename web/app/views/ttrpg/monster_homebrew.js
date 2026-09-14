// Homebrew monster form (new + edit): page data -> template -> verbatim
// monster_homebrew.html script (kind picker, randomizer, icon prompt, Gemini).
import { render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { loadScripts } from '../../lib/loader.js';
import { toast } from '../../ui/toast.js';
import { render as tpl } from './monster_homebrew_page/template.js';
import { init } from './monster_homebrew_page/script.js';

export const title = ctx => (ctx.params.id ? 'Edit Homebrew' : 'New Homebrew');

export async function mount(outlet, ctx) {
  const url = ctx.params.id ? `/api/v1/monsters/homebrew/${ctx.params.id}` : '/api/v1/monsters/homebrew/new';
  const [d] = await Promise.all([api.get(url), loadScripts(['/legacy/paste_image.js', '/legacy/ai_generate.js', '/legacy/asset_picker.js'])]);
  if (d.redirect) { if (d.message) toast.warn(d.message); return ctx.navigate(d.redirect, { replace: true }); }
  render(outlet, tpl(d));
  const dispose = init(ctx, d, { ICON_GENRES: d.icon_genres });
  const BS = window.bootstrap;
  ctx.cleanup(() => { dispose(); const m = outlet.querySelector('#iconPromptModal'); const inst = m && BS.Modal.getInstance(m); if (inst) inst.dispose(); document.querySelectorAll('.modal-backdrop').forEach(b => b.remove()); document.body.classList.remove('modal-open'); });
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    const btn = f.querySelector('button[type=submit]'); if (btn) btn.disabled = true;
    const err = outlet.querySelector('#hb-error');
    try {
      const r = await api.upload(f.dataset.api, new FormData(f), { quiet: true });
      if (r && r.message) toast.success(r.message);
      ctx.navigate('/ttrpg/monsters');
    } catch (x) {
      if (btn) btn.disabled = false;
      if (err) { err.textContent = x.message || 'Save failed'; err.style.display = ''; }
    }
  });
}

// Broadcast (OBS) view: page data -> template -> verbatim console.js.
import { render } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { loadScripts } from '../../../lib/loader.js';
import { toast } from '../../../ui/toast.js';
import { render as tpl } from './template.js';
import { init } from './console.js';

export const title = 'Broadcast';
const SCROLL_KEY = 'obsCfgScroll';

export async function mount(outlet, ctx) {
  const [d] = await Promise.all([api.get('/api/v1/obs/page'),
    loadScripts(['/legacy/paste_image.js', '/legacy/asset_picker.js'])]);
  document.title = 'Broadcast — ScenePlay';
  render(outlet, tpl(d));
  const G = { CARD_BASE_SUGGESTED: d.cfg.card_base_suggested, MUSIC_AUTO: d.music_auto, MAP_MODE: d.cfg.map_mode };
  const dispose = init(ctx, d, G);
  // A re-mount after a build/reorder/room change lands where the DM was
  // (console.js's _obsReload stashes the position, as the old form posts did).
  let raw = null;
  try { raw = sessionStorage.getItem(SCROLL_KEY); sessionStorage.removeItem(SCROLL_KEY); } catch (e) {}
  if (raw !== null) {
    const y = parseInt(raw, 10) || 0;
    window.scrollTo(0, y);
    ctx.after(150, () => window.scrollTo(0, y));   // again once the art has laid out
  }
  const BS = window.bootstrap;
  ctx.cleanup(() => {
    dispose();
    outlet.querySelectorAll('.modal').forEach(m => { const i = BS && BS.Modal.getInstance(m); if (i) i.dispose(); });
    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
    document.body.classList.remove('modal-open');
  });
  // The old form+redirect endpoints (toggle, art clear, "back to the shared
  // look"): submit as JSON/multipart, toast, re-mount. The submitter button's
  // name=value (the Clear buttons) rides along like a browser submit would.
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const btn = e.submitter || f.querySelector('button[type=submit], button:not([type])'); if (btn) btn.disabled = true;
    try {
      const fd = new FormData(f, e.submitter || undefined);
      const r = f.dataset.multipart ? await api.upload(f.dataset.api, fd) : await api.post(f.dataset.api, Object.fromEntries(fd.entries()));
      if (r && r.message) toast.success(r.message);
      try { sessionStorage.setItem(SCROLL_KEY, String(window.scrollY)); } catch (x) {}
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });
}

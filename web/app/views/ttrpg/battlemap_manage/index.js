// Map manager view: page data -> template -> verbatim manage.js.
import { render } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { loadScripts } from '../../../lib/loader.js';
import { toast } from '../../../ui/toast.js';
import { render as tpl } from './template.js';
import { init } from './manage.js';

export const title = 'Battle Maps';

export async function mount(outlet, ctx) {
  const sid = ctx.params.id;
  const [d] = await Promise.all([api.get(`/api/v1/battlemap/session/${sid}/page`),
    loadScripts(['/legacy/floorplan_prompt.js', '/legacy/paste_image.js', '/legacy/ai_generate.js', '/legacy/texture_picker.js', '/legacy/asset_picker.js'])]);
  document.title = `Battle Maps — ${d.sess.title} — ScenePlay`;
  render(outlet, tpl(d));
  const G = {
    SESSION_ID: sid, MAP_GENRES: d.map_prompt_data,
    FP_INFO: Object.fromEntries(d.maps.filter(m => m.floorplan).map(m => [String(m.map_id), m.floorplan])),
    BG_PASTE_URLS: Object.fromEntries(d.maps.map(m => [String(m.map_id), `/ttrpg/battlemap/${m.map_id}/bg-paste`])),
  };
  const dispose = init(ctx, d, G);
  const BS = window.bootstrap;
  ctx.cleanup(() => { dispose(); outlet.querySelectorAll('.modal').forEach(m => { const i = BS.Modal.getInstance(m); if (i) i.dispose(); }); document.querySelectorAll('.modal-backdrop').forEach(b => b.remove()); document.body.classList.remove('modal-open'); });
  // the old form+redirect endpoints: submit as JSON/multipart, toast, re-render
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const btn = f.querySelector('button[type=submit], button:not([type])'); if (btn) btn.disabled = true;
    try {
      const r = f.dataset.multipart ? await api.upload(f.dataset.api, new FormData(f)) : await api.post(f.dataset.api, Object.fromEntries(new FormData(f).entries()));
      if (r && r.message) toast.success(r.message);
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });
}

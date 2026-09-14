// Battle map view: page data -> template -> verbatim map.js (+ BMFP for the DM).
import { render } from '../../../lib/dom.js';
import { api, ApiError } from '../../../api.js';
import { loadScripts, loadScript } from '../../../lib/loader.js';
import { exposeGlobals, unexposeGlobals } from '../../../lib/legacy.js';
import { toast } from '../../../ui/toast.js';
import { render as tpl, globals } from './template.js';
import { init } from './map.js';

export const title = 'Battle Map';
let _mounts = 0;
const SFX_CTRL = '/legacy/sfx-control.js';

export async function mount(outlet, ctx) {
  const id = ctx.params.id;
  let d;
  try { d = await api.get(`/api/v1/battlemap/${id}/page`, { quiet: true }); }
  catch (e) { if (e instanceof ApiError && e.status === 404) { toast.error('That map no longer exists.'); return ctx.navigate('/ttrpg/battlemap/active', { replace: true }); } throw e; }
  if (d.redirect_map_id) return ctx.navigate(`/ttrpg/battlemap/${d.redirect_map_id}/view`, { replace: true });
  if (d.redirect) { toast.info(d.message || ''); return ctx.navigate(d.redirect, { replace: true }); }
  await loadScripts(['/shared/Tone.js', '/shared/dice.js', '/shared/sfx.js']);
  document.title = `${d.bm.name} — Battle Map — ScenePlay`;
  render(outlet, tpl(d));
  const G = globals(d);
  // BMFP (classic script) reads MAP_ID / GRID_* / CELL_PX / IS_DM from window at call time
  const gnames = Object.keys(G);
  exposeGlobals(G);
  const dispose = init(ctx, d, G);
  if (d.is_dm) {
    await loadScript('/legacy/battlemap_fp.js');
    try { if (window.BMFP && !window.BMFP.isDirty()) window.BMFP.revert(); } catch (e) {}   // fresh plan for THIS map
  }
  loadScript(SFX_CTRL + '?m=' + (++_mounts)).catch(() => {});
  ctx.cleanup(() => {
    try { if (window.BMFP) { if (window.BMFP.isDirty()) window.BMFP.save(); window.BMFP.close(); } } catch (e) {}
    dispose();
    unexposeGlobals(gnames);
    document.querySelectorAll('.tooltip, .popover, .fp-tex-menu').forEach(el => el.remove());
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
  });
}

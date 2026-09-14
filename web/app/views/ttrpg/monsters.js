// Monsters & Assets library view: page data -> template -> verbatim
// monsters.html script (search, stat block, add-to-session, homebrew tools).
import { render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { loadScripts } from '../../lib/loader.js';
import { toast } from '../../ui/toast.js';
import { startSync } from './reference/_sync.js';
import { render as tpl } from './monsters_page/template.js';
import { init } from './monsters_page/script.js';

export const title = 'Monsters & Assets';

export async function mount(outlet, ctx) {
  const [d] = await Promise.all([api.get('/api/v1/monsters/page'), loadScripts(['/legacy/paste_image.js', '/legacy/asset_picker.js'])]);
  render(outlet, tpl(d));
  const dispose = init(ctx, d, {});
  ctx.cleanup(dispose);
  ctx.on(outlet, 'click', e => {
    if (e.target.closest('[data-action="sync"]')) startSync(ctx, 'monsters', '/ttrpg/monsters/sync', '/ttrpg/monsters/sync/status');
  });
  // "Delete Homebrew" (the old form+redirect): the script points the form at the monster
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    if (!f.dataset.api) return;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const btn = f.querySelector('button'); if (btn) btn.disabled = true;
    try {
      const r = await api.post(f.dataset.api);
      if (r && r.message) toast.success(r.message);
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });
}

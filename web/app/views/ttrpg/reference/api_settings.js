// D&D API settings view: page data -> template -> verbatim api_settings.html
// script (syncAll / selectOption / testApi) wrapped by scripts/wrap_p5_js.py.
import { render } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { render as tpl } from './api_settings_page/template.js';
import { init } from './api_settings_page/script.js';

export const title = 'D&D API Settings';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/reference/settings');
  render(outlet, tpl(d));
  const dispose = init(ctx, d, { SYNC_JOBS: d.sync_jobs, CURRENT: d.current });
  ctx.cleanup(dispose);
  // the old form+redirect endpoints (clear libraries, save settings): toast + re-render
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('form[data-api]'); if (!f) return;
    e.preventDefault();
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const btn = f.querySelector('button[type=submit], button:not([type])'); if (btn) btn.disabled = true;
    try {
      const r = await api.post(f.dataset.api, Object.fromEntries(new FormData(f).entries()));
      if (r && r.message) toast.success(r.message);
      ctx.reload();
    } catch (x) { if (btn) btn.disabled = false; }
  });
}

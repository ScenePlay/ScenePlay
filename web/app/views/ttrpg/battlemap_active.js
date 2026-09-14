// /ttrpg/battlemap/active: jump to the live map (players), else fall back.
import { api } from '../../api.js';
import { toast } from '../../ui/toast.js';

export const title = 'Battle Map';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/battlemap/active');
  if (d.map_id) return ctx.navigate('/ttrpg/battlemap/' + d.map_id + '/view', { replace: true });
  toast.info(d.message || 'No active battle map right now.');
  ctx.navigate(d.is_dm ? '/ttrpg/battlemap/maps' : '/ttrpg/my-character', { replace: true });
}

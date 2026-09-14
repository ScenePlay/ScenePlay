// /ttrpg/battlemap/monster-redirect/:id -> the monster card for that instance.
import { api } from '../../api.js';

export const title = 'Monster';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/battlemap/monster-redirect/' + ctx.params.id);
  ctx.navigate(d.redirect, { replace: true });
}

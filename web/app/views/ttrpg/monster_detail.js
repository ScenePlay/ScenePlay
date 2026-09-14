// Monster card view (/ttrpg/monsters/:id/view?instance=): page data ->
// template -> verbatim monster_detail.html roller script over DiceCore.
import { render } from '../../lib/dom.js';
import { api } from '../../api.js';
import { loadScripts } from '../../lib/loader.js';
import { render as tpl } from './monster_detail_page/template.js';
import { init } from './monster_detail_page/script.js';

export const title = 'Monster';

export async function mount(outlet, ctx) {
  const inst = ctx.query.instance ? `?instance=${encodeURIComponent(ctx.query.instance)}` : '';
  const [d] = await Promise.all([api.get(`/api/v1/monsters/${ctx.params.id}/view-page${inst}`), loadScripts(['/shared/dice.js'])]);
  document.title = `${d.m.name} — ScenePlay`;
  render(outlet, tpl(d));
  const G = { MD_NAME: d.sm ? d.sm.display_name : d.m.name, MD_INSTANCE: d.sm ? d.sm.monster_id : null, MD_HP_MAX: d.sm ? d.sm.hp_max : 0, GAME_INFO: d.game };
  const dispose = init(ctx, d, G);
  ctx.cleanup(dispose);
}

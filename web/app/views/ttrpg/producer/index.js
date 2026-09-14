// Producer console (/ttrpg/producer): a second person runs the stream from
// their own laptop. Spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md
import { render } from '../../../lib/dom.js';
import { loadCss } from '../../../lib/loader.js';
import { api } from '../../../api.js';
import { sse } from '../../../sse.js';
import { store } from '../../../store.js';
import { render as tpl } from './template.js';
import { createConsole } from './console.js';

export const title = 'Producer console';

const P = '/ttrpg/producer/api';
let consoleId = null;
const offs = [];

export async function mount(outlet, ctx) {
  await loadCss('/css/views/producer.css');
  const d = await api.get(`${P}/state`);
  render(outlet, tpl(d));
  const c = createConsole(ctx, outlet);
  c.paintState(d);
  c.wire();
  const opened = await api.post(`${P}/session`);
  consoleId = opened.console_id;

  let player = { volume: 0 };
  try { player = await api.get('/api/v1/player', { quiet: true }); } catch (e) {}
  c.setVolume(player.volume);

  const refresh = async () => { try { c.paintState(await api.get(`${P}/state`, { quiet: true })); } catch (e) {} };
  offs.push(sse.subscribe('producer', refresh, { fallback: { every: 5000, fetch: refresh } }));
  offs.push(sse.subscribe('obs', refresh));
  offs.push(sse.subscribe('queue', q => c.setSceneStates(q && q.scene_states),
    { fallback: { every: 5000, fetch: () => api.get('/api/scenes/queue-states', { quiet: true }).then(r => ({ scene_states: r.states })) } }));
  offs.push(store.subscribe('nowPlaying', np => c.setNowPlaying(np), { immediate: true }));

  await Promise.all([c.loadScenes(), c.loadRows()]);
  ctx.every(500, () => c.snapMonitors());
  ctx.every(3000, () => c.snapTiles());
  ctx.every(250, async () => { if (document.hidden) return; try { const l = await api.get(`${P}/levels`, { quiet: true }); c.paintLevels(l.levels || {}); } catch (e) {} });
  ctx.every(1000, () => c.tickClocks());
  ctx.every(15000, () => api.post(`${P}/session/ping`, { console_id: consoleId }).catch(() => {}));
  c.snapMonitors(); c.snapTiles(); c.tickClocks();
}

export function unmount() {
  for (const off of offs.splice(0)) { try { off(); } catch (e) {} }
  if (consoleId) { api.del(`${P}/session/${consoleId}`).catch(() => {}); consoleId = null; }
}

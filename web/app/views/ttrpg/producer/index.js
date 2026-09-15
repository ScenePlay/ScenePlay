// Producer console (/ttrpg/producer): a second person runs the stream from
// their own laptop. Spec: docs/superpowers/specs/2026-09-14-producer-console-core-design.md
import { render } from '../../../lib/dom.js';
import { loadCss } from '../../../lib/loader.js';
import { api } from '../../../api.js';
import { render as tpl } from './template.js';
import { createConsole } from './console.js';

export const title = 'Producer console';

const P = '/ttrpg/producer/api';
// Bumped by every mount AND every unmount. A mount that is still awaiting a
// fetch when the user navigates away finds its token stale, closes whatever
// session it opened and registers no timers or subscriptions.
let mountSeq = 0;
let session = null;          // the session object the live mount owns

function closeSession(id) {
  if (id) api.del(`${P}/session/${id}`, { quiet: true }).catch(() => {});
}

export async function mount(outlet, ctx) {
  const my = ++mountSeq;
  await loadCss('/css/views/producer.css');
  const d = await api.get(`${P}/state`);
  if (my !== mountSeq) return;
  render(outlet, tpl(d));
  const c = createConsole(ctx, outlet);
  c.paintState(d);
  c.wire();
  const opened = await api.post(`${P}/session`);
  if (my !== mountSeq) { closeSession(opened.console_id); return; }
  const mine = { id: opened.console_id };
  session = mine;

  let player = { volume: 0 };
  try { player = await api.get('/api/v1/player', { quiet: true }); } catch (e) {}
  if (my !== mountSeq) { closeSession(mine.id); session = null; return; }
  c.setVolume(player.volume);
  if (player.nowplaying) c.setNowPlaying(player.nowplaying);

  // One debounced repaint for both topics: a Take emits `producer` and `obs`
  // milliseconds apart, and two consoles double that again — a full state
  // fetch per event is pure amplification. The OBS audio rows (mute state)
  // ride the same refresh, since nothing else would notice a mute.
  let timer = null;
  const fetchAndPaint = async () => {
    timer = null;
    if (mine !== session) return;
    try { c.paintState(await api.get(`${P}/state`, { quiet: true })); } catch (e) {}
    c.loadRows();
  };
  const refresh = (data) => {
    if (data && Array.isArray(data.shots)) {    // the fallback poll fetched it already
      c.paintState(data);
      c.loadRows();
      return;
    }
    if (timer === null) timer = setTimeout(fetchAndPaint, 200);
  };
  ctx.cleanup(() => { if (timer !== null) clearTimeout(timer); });

  ctx.subscribe('producer', refresh,
    { fallback: { every: 5000, fetch: () => api.get(`${P}/state`, { quiet: true }) } });
  ctx.subscribe('obs', refresh);
  ctx.subscribe('queue', q => c.setSceneStates(q && q.scene_states),
    { fallback: { every: 5000, fetch: () => api.get('/api/scenes/queue-states', { quiet: true }).then(r => ({ scene_states: r.states })) } });
  // `nowplaying` carries the track AND the active ScenePlay scene. The media
  // layout's player bar (which fills store.nowPlaying) is not on this page.
  ctx.subscribe('nowplaying', np => c.setNowPlaying(np),
    { fallback: { every: 5000, fetch: () => api.get('/api/nowplaying', { quiet: true }) } });
  // a scene activation changes colours, queue state and which tile is live
  ctx.subscribe('scene', () => c.loadScenes());

  await Promise.all([c.loadScenes(), c.loadRows()]);
  ctx.every(500, () => c.snapMonitors());
  ctx.every(3000, () => c.snapTiles());
  ctx.every(250, async () => { if (document.hidden) return; try { const l = await api.get(`${P}/levels`, { quiet: true }); c.paintLevels(l.levels || {}); } catch (e) {} });
  ctx.every(1000, () => c.tickClocks());
  ctx.every(15000, async () => {
    if (mine !== session) return;
    try {
      const r = await api.post(`${P}/session/ping`, { console_id: mine.id }, { quiet: true });
      if (r && r.ok === false) {
        // Reaped while this tab slept (or the network dropped): register
        // again, or Studio Mode goes off under a console still on screen.
        const again = await api.post(`${P}/session`, {}, { quiet: true });
        if (mine !== session) { closeSession(again.console_id); return; }
        mine.id = again.console_id;
      }
    } catch (e) {}
  });
  c.snapMonitors(); c.snapTiles(); c.tickClocks();
}

export function unmount() {
  mountSeq++;                       // supersede a mount still in flight
  const mine = session;
  session = null;
  if (mine) closeSession(mine.id);
}

// Boot: theme, fetch shim, auth restore, bootstrap payload, SSE, router.
import { installFetchShim } from './lib/fetch_shim.js';
import { store } from './store.js';
import * as auth from './auth.js';
import { api } from './api.js';
import { sse } from './sse.js';
import { defineRoutes, start, navigate } from './router.js';
import { routes, layouts } from './routes.js';
import { applyOnAccent, wireOutsideClose } from './theme.js';
import { toast } from './ui/toast.js';
import './ui/pick_option.js';

async function boot() {
  applyOnAccent();
  wireOutsideClose();
  installFetchShim();
  defineRoutes(routes, layouts);

  auth.onExpired(reason => {
    if (reason === 'expired') toast.warn('Your session expired — please log in again.');
    if (location.pathname !== '/login') {
      try { if (reason === 'expired') sessionStorage.setItem('sp_return', location.pathname + location.search); } catch (e) {}
      navigate('/login', { replace: true });
    }
  });

  if (!auth.isValid()) auth.clear();
  let bs = null;
  try { bs = await api.get('/api/v1/auth/bootstrap', { quiet: true }); } catch (e) { bs = null; }
  if (bs) {
    store.set('user', bs.user);
    store.set('setupNeeded', !!bs.setup_needed);
    store.set('sceneplayLocked', !!bs.sceneplay_locked);
    store.set('keepMusic', !!bs.keep_music);
    store.set('health', bs.health);
    store.set('serverInfo', { version: bs.version, workers: bs.workers !== false, player: bs.player_engine || 'classic' });
    if (!bs.user && auth.token()) auth.clear();
  }

  // navbar pills + version stay live through SSE (topics subscribed for the
  // life of the tab; the layouts just read the store)
  sse.start();
  const health = () => sse.subscribe('health', h => store.set('health', h));
  const server = () => sse.subscribe('server', v => { if (v && v.version) store.set('serverInfo', { version: v.version }); });
  if (store.get('user')) { health(); server(); }
  store.subscribe('user', u => { if (u) { health(); server(); } });
  auth.startRefreshTimer();

  await start(document.getElementById('shell'));
}

boot().catch(e => {
  console.error(e);
  const s = document.getElementById('sp-boot');
  if (s) s.textContent = 'ScenePlay failed to start: ' + (e.message || e);
});

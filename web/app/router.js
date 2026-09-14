// History-API router: route table, params, guards, layouts, view lifecycle.
import { store } from './store.js';
import * as auth from './auth.js';
import { api } from './api.js';
import { sse } from './sse.js';
import { toast } from './ui/toast.js';

const NATIVE_PREFIXES = ['/static/', '/assets/', '/backups/', '/ttrpg/obs/tile', '/ttrpg/obs/card',
  '/ttrpg/obs/panel', '/ttrpg/obs/map', '/docs', '/restarting.html'];
const NATIVE_RE = [/^\/handouts\/\d+\/file/];

let _routes = [], _layouts = {}, _current = null, _layoutName = null, _layoutMod = null, _shell = null, _outlet = null;
let _navSeq = 0;

function _compile(path) {
  const keys = [];
  const re = path.replace(/[.*+?^${}()|[\]\\]/g, m => (m === '*' ? '(.*)' : '\\' + m))
    .replace(/:([A-Za-z_]+)/g, (_, k) => { keys.push(k); return '([^/]+)'; });
  return { re: new RegExp('^' + re + '/?$'), keys };
}

export function defineRoutes(list, layouts) {
  _routes = list.map(r => ({ ...r, ..._compile(r.path) }));
  _layouts = layouts;
}

function _match(pathname) {
  for (const r of _routes) {
    const m = r.re.exec(pathname);
    if (!m) continue;
    const params = {};
    r.keys.forEach((k, i) => { const v = decodeURIComponent(m[i + 1]); params[k] = /^\d+$/.test(v) ? Number(v) : v; });
    if (m.length > r.keys.length + 1) params.rest = m[m.length - 1];
    return { route: r, params };
  }
  return null;
}

function _query(search) { const q = {}; new URLSearchParams(search).forEach((v, k) => { q[k] = v; }); return q; }

function _makeCtx(route, params, query, seq) {
  const cleanups = [];
  const ac = new AbortController();
  const ctx = {
    params, query, route, path: location.pathname + location.search,
    get user() { return store.get('user'); },
    store, api, sse,
    signal: ac.signal,
    navigate, reload: () => resolve(true),
    on(target, ev, fn, opts) { target.addEventListener(ev, fn, opts); cleanups.push(() => target.removeEventListener(ev, fn, opts)); return fn; },
    every(ms, fn) { const id = setInterval(fn, ms); cleanups.push(() => clearInterval(id)); return id; },
    after(ms, fn) { const id = setTimeout(fn, ms); cleanups.push(() => clearTimeout(id)); return id; },
    subscribe(topic, handler, opts) { const off = sse.subscribe(topic, handler, opts); cleanups.push(off); return off; },
    watch(key, fn, opts) { const off = store.subscribe(key, fn, opts); cleanups.push(off); return off; },
    cleanup(fn) { cleanups.push(fn); },
    _dispose() { ac.abort(); for (const c of cleanups.splice(0)) { try { c(); } catch (e) { console.error(e); } } },
    _seq: seq,
  };
  return ctx;
}

async function _unmountCurrent() {
  if (!_current) return;
  const cur = _current; _current = null;
  try { if (cur.mod && cur.mod.unmount) await cur.mod.unmount(cur.ctx); } catch (e) { console.error(e); }
  cur.ctx._dispose();
  if (cur.route.bodyClass) document.body.classList.remove(cur.route.bodyClass);
}

async function _ensureLayout(name) {
  if (_layoutName === name && _layoutMod) return;
  if (_layoutMod && _layoutMod.unmount) { try { _layoutMod.unmount(); } catch (e) { console.error(e); } }
  _layoutMod = null; _layoutName = null;
  const mod = await _layouts[name]();
  _shell.innerHTML = '';
  _outlet = await mod.mount(_shell);
  _layoutMod = mod; _layoutName = name;
}

export async function resolve(isReload = false) {
  const seq = ++_navSeq;
  const pathname = location.pathname;
  const m = _match(pathname);
  const route = m ? m.route : { path: pathname, view: () => import('./views/not_found.js'), layout: 'chromeless', auth: 'none' };
  const params = m ? m.params : {};
  const query = _query(location.search);

  // guards
  const user = store.get('user');
  if (store.get('setupNeeded') && pathname !== '/ttrpg/setup') { return navigate('/ttrpg/setup', { replace: true }); }
  if ((route.auth === 'user' || route.auth === 'dm') && !user) {
    try { sessionStorage.setItem('sp_return', pathname + location.search); } catch (e) {}
    return navigate('/login', { replace: true });
  }
  if (route.auth === 'dm' && user.role !== 'dm') {
    toast.warn('That page is DM-only.');
    return navigate('/ttrpg/my-character', { replace: true });
  }
  let view = route.view;
  if (route.auth === 'sceneplay' && store.get('sceneplayLocked') && !(user && user.role === 'dm')) {
    view = () => import('./layouts/locked.js');
  }

  await _unmountCurrent();
  await _ensureLayout(route.layout || 'chromeless');
  if (seq !== _navSeq) return;
  const mod = await view();
  if (seq !== _navSeq) return;
  const ctx = _makeCtx(route, params, query, seq);
  if (route.bodyClass) document.body.classList.add(route.bodyClass);
  _outlet.innerHTML = '';
  if (!isReload) window.scrollTo(0, 0);
  _current = { route, mod, ctx };
  const t = typeof mod.title === 'function' ? mod.title(ctx) : mod.title;
  document.title = t ? `${t} — ScenePlay` : 'ScenePlay';
  try {
    await mod.mount(_outlet, ctx);
  } catch (e) {
    if (e && e.name === 'AbortError') return;
    console.error('view mount failed', pathname, e);
    if (!(e && e.status)) _outlet.innerHTML = `<div class="alert alert-danger m-3">This page failed to load: ${String(e.message || e)}</div>`;
  }
  const hd = _outlet.querySelector('h1,h2,h3');
  if (hd && !isReload) { hd.setAttribute('tabindex', '-1'); try { hd.focus({ preventScroll: true }); } catch (e) {} }
}

export function navigate(url, { replace = false } = {}) {
  const u = new URL(url, location.href);
  if (u.origin !== location.origin) { location.href = url; return; }
  if (replace) history.replaceState({}, '', u.pathname + u.search + u.hash);
  else history.pushState({}, '', u.pathname + u.search + u.hash);
  return resolve();
}

export function isNativePath(p) { return NATIVE_PREFIXES.some(x => p.startsWith(x)) || NATIVE_RE.some(r => r.test(p)); }

export function start(shell) {
  _shell = shell;
  window.addEventListener('popstate', () => resolve());
  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target || a.hasAttribute('download') || a.hasAttribute('data-native')) return;
    const href = a.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || isNativePath(u.pathname)) return;
    e.preventDefault();
    navigate(u.pathname + u.search + u.hash);
  });
  window.spReload = () => resolve(true);
  window.spNavigate = navigate;
  return resolve();
}

export function current() { return _current; }
export function debugLeaks() { return _current ? { route: _current.route.path } : null; }

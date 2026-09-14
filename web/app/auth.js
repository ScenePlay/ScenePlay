// JWT persistence + login/logout + expiry handling.
import { store } from './store.js';

const KEY = 'sp_jwt';
let _onExpired = null;       // set by main.js: navigate to /login
let _expiredOnce = false;

export function token() {
  try { return localStorage.getItem(KEY) || sessionStorage.getItem(KEY) || null; } catch (e) { return null; }
}

export function parseJwt(t) {
  try {
    const b = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(atob(b).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')));
  } catch (e) { return null; }
}

export function claims() { const t = token(); return t ? parseJwt(t) : null; }
export function isValid() { const c = claims(); return !!(c && c.exp && c.exp * 1000 > Date.now() + 30000); }
export function role() { const c = claims(); return c ? c.role : null; }

export function storeToken(t, remember = true) {
  try {
    localStorage.removeItem(KEY); sessionStorage.removeItem(KEY);
    (remember ? localStorage : sessionStorage).setItem(KEY, t);
  } catch (e) {}
  _expiredOnce = false;
}

export function clear() {
  try { localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); } catch (e) {}
  store.set('user', null);
}

export async function login(username, password, remember = true, ttlHours = null) {
  const { api } = await import('./api.js');
  const body = { username, password };
  if (!remember) body.ttl_hours = ttlHours || 12;
  const res = await api('POST', '/api/v1/auth/login', body, { quiet: true, noAuth: true });
  storeToken(res.token, remember);
  store.set('user', res.user);
  const { sse } = await import('./sse.js');
  sse.reconnect();
  return res;
}

export function logout() {
  clear();
  import('./sse.js').then(({ sse }) => sse.close());
  if (_onExpired) _onExpired('logout');
}

export function onExpired(fn) { _onExpired = fn; }

export function expired(msg) {
  if (_expiredOnce) return;
  _expiredOnce = true;
  clear();
  import('./sse.js').then(({ sse }) => sse.close());
  if (_onExpired) _onExpired(msg || 'expired');
}

// Proactive renewal: every 5 min, refresh when the token is older than a day
// or has less than 30 min left (players keep phones open all night).
export function startRefreshTimer() {
  const tick = async () => {
    const c = claims();
    if (!c) return;
    const ageS = Date.now() / 1000 - (c.iat || 0), leftS = (c.exp || 0) - Date.now() / 1000;
    if (ageS < 86400 && leftS > 1800) return;
    try {
      const { api } = await import('./api.js');
      const res = await api('POST', '/api/v1/auth/refresh', null, { quiet: true });
      let remembered = true;
      try { remembered = !!localStorage.getItem(KEY); } catch (e) {}
      storeToken(res.token, remembered);
    } catch (e) { /* a 401 already routed to expired() */ }
  };
  setInterval(tick, 5 * 60 * 1000);
  tick();
}

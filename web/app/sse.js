// One EventSource per tab with topic subscriptions, manual backoff, revive
// after bfcache/visibility, and per-subscriber fallback polls while down.
import * as auth from './auth.js';
import { store } from './store.js';
import { topicOk } from './topics.js';

const _subs = new Map();          // topic -> Set(sub)
let _es = null, _state = 'down', _retryMs = 1000, _timer = null, _rebuild = null, _lastId = null, _downSince = 0;
const _fallbackTimers = new Map();

function _setState(s) { if (_state !== s) { _state = s; store.set('sseState', s); if (s === 'ok') _stopFallbacks(); else if (!_downSince) _downSince = Date.now(); if (s === 'ok') _downSince = 0; _scheduleFallbacks(); } }

function _topicsWanted() { return Array.from(_subs.keys()).filter(t => _subs.get(t).size); }

function _dispatch(topic, data, id) {
  if (id) _lastId = id;
  for (const s of _subs.get(topic) || []) { try { s.handler(data, topic); } catch (e) { console.error('sse handler', topic, e); } }
}

function _connect() {
  _close(false);
  const topics = _topicsWanted();
  const tok = auth.token();
  if (!topics.length || !tok || !auth.isValid()) { _setState('down'); return; }
  const url = `/api/v1/events?topics=${encodeURIComponent(topics.join(','))}&token=${encodeURIComponent(tok)}` + (_lastId ? `&last_id=${_lastId}` : '');
  const es = new EventSource(url);
  _es = es;
  es.onopen = () => { _retryMs = 1000; _setState('ok'); };
  es.addEventListener('hello', ev => {
    let snaps = {}; try { snaps = JSON.parse(ev.data); } catch (e) {}
    for (const [t, v] of Object.entries(snaps)) if (t === 'server') _serverInfo(v); else if (_subs.has(t)) _dispatch(t, v);
    _setState('ok');
  });
  es.addEventListener('ping', () => {});
  for (const t of topics) es.addEventListener(t, ev => { let d = null; try { d = JSON.parse(ev.data); } catch (e) {} _dispatch(t, d, ev.lastEventId); });
  es.onerror = () => {
    es.close();
    if (_es === es) _es = null;
    _setState('reconnecting');
    _timer = setTimeout(_connect, _retryMs);
    _retryMs = Math.min(30000, _retryMs * 2);
  };
}

function _serverInfo(v) {
  const cur = store.get('serverInfo') || {};
  if (v && v.version && cur.version && v.version !== cur.version) {
    import('./ui/toast.js').then(({ toast }) => toast.warn(`ScenePlay was updated to ${v.version} — reload when convenient.`, { ms: 15000 }));
  }
}

function _close(setDown = true) {
  if (_timer) { clearTimeout(_timer); _timer = null; }
  if (_es) { try { _es.close(); } catch (e) {} _es = null; }
  if (setDown) _setState('down');
}

function _requestRebuild() {
  if (_rebuild) clearTimeout(_rebuild);
  _rebuild = setTimeout(() => { _rebuild = null; _connect(); }, 150);
}

function _stopFallbacks() { for (const t of _fallbackTimers.values()) clearInterval(t); _fallbackTimers.clear(); }
function _scheduleFallbacks() {
  if (_state === 'ok') return;
  for (const [topic, set] of _subs) for (const s of set) {
    if (!s.fallback || _fallbackTimers.has(s)) continue;
    const run = async () => {
      if (_state === 'ok') return;
      if (Date.now() - _downSince < 5000) return;
      try { const d = await s.fallback.fetch(); s.handler(d, topic); } catch (e) {}
    };
    _fallbackTimers.set(s, setInterval(run, s.fallback.every || 5000));
  }
}

export const sse = {
  get state() { return _state; },
  subscribe(topic, handler, { fallback = null } = {}) {
    if (!topicOk(topic)) console.warn('unknown SSE topic', topic);
    if (!_subs.has(topic)) _subs.set(topic, new Set());
    const sub = { handler, fallback };
    _subs.get(topic).add(sub);
    _requestRebuild();
    _scheduleFallbacks();
    return () => {
      const set = _subs.get(topic); if (set) set.delete(sub);
      const t = _fallbackTimers.get(sub); if (t) { clearInterval(t); _fallbackTimers.delete(sub); }
      _requestRebuild();
    };
  },
  reconnect() { _lastId = null; _retryMs = 1000; _connect(); },
  close() { _close(true); _stopFallbacks(); },
  start() {
    window.addEventListener('pageshow', e => { if (e.persisted) this.reconnect(); });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && _state !== 'ok' && _topicsWanted().length) _connect(); });
    window.addEventListener('online', () => { if (_topicsWanted().length) _connect(); });
  },
};

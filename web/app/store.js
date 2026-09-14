// Minimal observable key/value store shared by layouts and views.
const _data = {
  user: null, serverInfo: {}, sceneplayLocked: false, keepMusic: false,
  nowPlaying: null, queueCounts: null, health: null, sseState: 'down', setupNeeded: false,
};
const _subs = new Map();

function _same(a, b) { try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return a === b; } }

export const store = {
  get(k) { return _data[k]; },
  set(k, v) {
    if (_same(_data[k], v)) return;
    _data[k] = v;
    for (const fn of _subs.get(k) || []) { try { fn(v); } catch (e) { console.error(e); } }
  },
  patch(k, partial) { this.set(k, Object.assign({}, _data[k] || {}, partial)); },
  subscribe(k, fn, { immediate = false } = {}) {
    if (!_subs.has(k)) _subs.set(k, new Set());
    _subs.get(k).add(fn);
    if (immediate) fn(_data[k]);
    return () => _subs.get(k).delete(fn);
  },
  isDm() { return !!(_data.user && _data.user.role === 'dm'); },
};

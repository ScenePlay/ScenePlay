// Deduped classic-script / stylesheet loading for vendor globals and the
// legacy helper scripts (three, Tone, battlemap3d, dice, sfx, ...).
const _scripts = new Map();
const _styles = new Map();

export function loadScript(src) {
  if (_scripts.has(src)) return _scripts.get(src);
  const p = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = false;
    s.onload = () => resolve(src);
    s.onerror = () => { _scripts.delete(src); reject(new Error('failed to load ' + src)); };
    document.head.appendChild(s);
  });
  _scripts.set(src, p);
  return p;
}

export function loadScripts(list) { return list.reduce((p, s) => p.then(() => loadScript(s)), Promise.resolve()); }

export function loadCss(href) {
  if (_styles.has(href)) return _styles.get(href);
  const p = new Promise((resolve) => {
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    l.onload = () => resolve(href);
    l.onerror = () => resolve(href);
    document.head.appendChild(l);
  });
  _styles.set(href, p);
  return p;
}

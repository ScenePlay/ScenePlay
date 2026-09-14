// Tiny DOM helpers. `html` is a tagged template that escapes interpolations
// unless they are wrapped with raw().
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = s => new Raw(s == null ? '' : String(s));

export function html(strings, ...vals) {
  let out = '';
  strings.forEach((s, i) => {
    out += s;
    if (i < vals.length) {
      const v = vals[i];
      if (v instanceof Raw) out += v.s;
      else if (Array.isArray(v)) out += v.map(x => (x instanceof Raw ? x.s : esc(x))).join('');
      else out += esc(v);
    }
  });
  return new Raw(out);
}

export function render(el, tpl) { el.innerHTML = tpl instanceof Raw ? tpl.s : String(tpl); return el; }

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function delegate(root, ev, sel, fn, opts) {
  const handler = e => { const t = e.target.closest && e.target.closest(sel); if (t && root.contains(t)) fn(e, t); };
  root.addEventListener(ev, handler, opts);
  return () => root.removeEventListener(ev, handler, opts);
}

export const bs = () => window.bootstrap;

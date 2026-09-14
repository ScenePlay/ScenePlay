// ONE shared floating panel with search + thumb rows (from site.js).
import { shortMediaName } from '../lib/format.js';

export { shortMediaName };
export function spSmallThumb(url) { return url ? url.replace('/maxresdefault.', '/mqdefault.') : null; }

let _cleanup = null;
export function spCloseMediaPicker() {
  const p = document.getElementById('spMediaPicker'); if (p) p.remove();
  if (_cleanup) { _cleanup(); _cleanup = null; }
}

// opts: {items, current, getId, getName, getThumb, getDur, onPick(id, itemOrNull)}
export function spOpenMediaPicker(anchor, opts) {
  spCloseMediaPicker();
  const panel = document.createElement('div'); panel.id = 'spMediaPicker';
  const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Filter…'; panel.appendChild(search);
  const list = document.createElement('div'); list.className = 'sp-picker-list'; panel.appendChild(list);
  const addRow = (id, name, thumb, dur, item) => {
    const row = document.createElement('div');
    row.className = 'sp-picker-row' + (parseInt(id) === parseInt(opts.current) ? ' current' : '');
    if (thumb) { const img = document.createElement('img'); img.src = thumb; img.loading = 'lazy'; row.appendChild(img); }
    const nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = name; row.appendChild(nm);
    if (dur) { const d = document.createElement('span'); d.className = 'dur'; d.textContent = dur; row.appendChild(d); }
    row.onclick = () => { spCloseMediaPicker(); opts.onPick(id, item); };
    list.appendChild(row);
  };
  addRow(0, '— none —', null, '', null);
  opts.items.forEach(it => addRow(opts.getId(it), opts.getName(it), opts.getThumb(it), opts.getDur ? opts.getDur(it) : '', it));
  document.body.appendChild(panel);
  const rect = anchor.getBoundingClientRect();
  let top = rect.bottom + 6;
  if (top + panel.offsetHeight > window.innerHeight - 8) top = Math.max(8, rect.top - panel.offsetHeight - 6);
  panel.style.top = top + 'px';
  panel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - panel.offsetWidth - 16)) + 'px';
  search.addEventListener('input', () => { const q = search.value.toLowerCase(); list.querySelectorAll('.sp-picker-row').forEach(r => { r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'; }); });
  search.focus();
  const cur = list.querySelector('.current'); if (cur) list.scrollTop = cur.offsetTop - list.clientHeight / 2;
  const onDocClick = ev => { if (!panel.contains(ev.target) && !anchor.contains(ev.target)) spCloseMediaPicker(); };
  const onKey = ev => { if (ev.key === 'Escape') spCloseMediaPicker(); };
  setTimeout(() => document.addEventListener('click', onDocClick), 0);
  document.addEventListener('keydown', onKey);
  _cleanup = () => { document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onKey); };
}

export function spSetPickerBtn(btn, name, thumb) {
  const img = btn.querySelector('img'), span = btn.querySelector('span');
  if (span) span.textContent = name;
  if (img) { if (thumb) { img.src = thumb; img.style.display = ''; } else img.style.display = 'none'; }
}

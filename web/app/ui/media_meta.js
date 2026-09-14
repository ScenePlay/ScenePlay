// /api/mediameta/<type>/<id> card: table Info modal + now-playing hover (from site.js).
import { fmtDur } from '../lib/format.js';
import { api } from '../api.js';

const _cache = {};
export function fetchMediaMeta(mediaType, mediaId) {
  const key = mediaType + '/' + mediaId;
  if (!_cache[key]) {
    _cache[key] = api.get('/api/mediameta/' + key, { quiet: true });
    _cache[key].catch(() => delete _cache[key]);
  }
  return _cache[key];
}

export function buildMetaCard(meta, opts = {}) {
  const card = document.createElement('div');
  if (!meta) { const p = document.createElement('p'); p.textContent = 'No metadata extracted for this item yet.'; p.style = 'margin:0;'; card.appendChild(p); return card; }
  if (meta.thumbnail) { const img = document.createElement('img'); img.src = meta.thumbnail; img.style = 'width:100%;border-radius:6px;margin-bottom:10px;'; card.appendChild(img); }
  const h = document.createElement(opts.hover ? 'h6' : 'h4'); h.textContent = meta.title || '(no title)'; card.appendChild(h);
  const rows = [
    ['Uploader', meta.uploader],
    ['Uploaded', meta.upload_date ? String(meta.upload_date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') : null],
    ['Length', fmtDur(meta.duration)],
    ['Views', meta.view_count != null ? Number(meta.view_count).toLocaleString() : null],
    ['Categories', meta.categories ? (() => { try { return JSON.parse(meta.categories).join(', '); } catch (e) { return meta.categories; } })() : null],
    ['Extracted', meta.extracted_at],
    ['Last error', meta.last_error],
  ];
  const tbl = document.createElement('table'); tbl.style = 'font-size:.9em;margin-bottom:10px;';
  rows.forEach(([label, val]) => {
    if (!val) return;
    const tr = document.createElement('tr');
    const td1 = document.createElement('td'); td1.textContent = label; td1.style = 'color:var(--sp-muted, #999);padding-right:12px;border:none;vertical-align:top;';
    const td2 = document.createElement('td'); td2.textContent = val; td2.style = 'border:none;';
    tr.append(td1, td2); tbl.appendChild(tr);
  });
  card.appendChild(tbl);
  if (meta.description) {
    const desc = document.createElement('div'); desc.textContent = meta.description;
    desc.style = 'white-space:pre-wrap;font-size:.85em;color:var(--sp-muted, #bbb);' + (opts.hover ? 'max-height:90px;overflow:hidden;' : 'max-height:200px;overflow-y:auto;');
    card.appendChild(desc);
  }
  return card;
}

export function showMediaMeta(mediaType, mediaId) {
  fetchMediaMeta(mediaType, mediaId).then(meta => {
    const old = document.getElementById('mediaMetaOverlay'); if (old) old.remove();
    const overlay = document.createElement('div'); overlay.id = 'mediaMetaOverlay';
    overlay.style = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1050;display:flex;align-items:center;justify-content:center;';
    overlay.onclick = ev => { if (ev.target === overlay) overlay.remove(); };
    const card = document.createElement('div');
    card.style = 'background:var(--sp-bg, #222);color:var(--sp-text, #eee);max-width:560px;width:90%;max-height:80vh;overflow-y:auto;border-radius:8px;padding:20px;';
    card.appendChild(buildMetaCard(meta));
    const close = document.createElement('button'); close.textContent = 'Close'; close.className = 'btn btn-secondary mt-2'; close.onclick = () => overlay.remove();
    card.appendChild(close); overlay.appendChild(card); document.body.appendChild(overlay);
  }).catch(err => console.error('mediameta fetch failed:', err));
}

export function hideMetaHover() { const old = document.getElementById('mediaMetaHover'); if (old) old.remove(); }

export function showMetaHover(anchor, mediaType, mediaId) {
  hideMetaHover();
  fetchMediaMeta(mediaType, mediaId).then(meta => {
    if (!anchor.matches(':hover')) return;
    hideMetaHover();
    const pop = document.createElement('div'); pop.id = 'mediaMetaHover';
    pop.style = 'position:fixed;z-index:1060;width:320px;max-height:70vh;overflow:hidden;background:var(--sp-bg, #222);color:var(--sp-text, #eee);border:1px solid var(--sp-muted, #555);border-radius:8px;padding:12px;box-shadow:0 4px 16px rgba(0,0,0,.5);pointer-events:none;';
    pop.appendChild(buildMetaCard(meta, { hover: true }));
    document.body.appendChild(pop);
    const rect = anchor.getBoundingClientRect();
    let top = rect.bottom + 8;
    if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, rect.top - pop.offsetHeight - 8);
    pop.style.top = top + 'px';
    pop.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 336)) + 'px';
  }).catch(err => console.error('mediameta fetch failed:', err));
}

window.showMediaMeta = showMediaMeta;
window.showMetaHover = showMetaHover;
window.hideMetaHover = hideMetaHover;

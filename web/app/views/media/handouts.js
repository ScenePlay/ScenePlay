// Handouts list (templates/handouts.html): upload a PDF, rename, delete,
// open the reader (bookmarks link straight to a page), download.
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';
import { toast } from '../../ui/toast.js';

export const title = 'Handouts';

const STYLE = `<style>
  .sp-handouts table { width:100%; font-size:.9em; border-collapse:collapse; }
  .sp-handouts th, .sp-handouts td { padding:6px 8px; border-bottom:1px solid var(--sp-border); vertical-align:middle; }
  .sp-handouts th { text-align:left; }
  .sp-handouts td.num { text-align:right; white-space:nowrap; }
  .sp-handouts .muted { color:var(--sp-muted); }
  .sp-handouts .missing td { opacity:.55; }
  .sp-handouts .actions { white-space:nowrap; text-align:right; }
  .sp-handouts .actions .btn { margin-left:4px; }
  .sp-handouts .upload-row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .sp-handouts .upload-row input[type=text] { max-width:320px; }
  .sp-handouts .upload-row input[type=file] { max-width:360px; }
  .sp-handouts .title-cell { cursor:text; }
  .sp-handouts .title-cell:hover { text-decoration:underline dotted; }
  .sp-handouts .marks { display:flex; flex-wrap:wrap; gap:4px; margin-top:3px; }
  .sp-handouts .marks a { font-size:.78em; padding:1px 7px; border-radius:10px; border:1px solid var(--sp-border); background:var(--sp-surface-2, transparent); text-decoration:none; color:inherit; white-space:nowrap; max-width:180px; overflow:hidden; text-overflow:ellipsis; }
  .sp-handouts .marks a::before { content:"\\1F516"; margin-right:3px; opacity:.7; }
  .sp-handouts .marks a:hover { border-color:var(--sp-accent, #b83a2c); }
  .sp-handouts .marks .more { font-size:.78em; color:var(--sp-muted); align-self:center; }
</style>`;

function page(d) {
  const hs = d.handouts;
  return html`${raw(STYLE)}<div class="sp-page sp-handouts">
  <div class="sp-page-head"><h1>Handouts</h1><a href="/utilities" style="font-size:.85em;">&larr; Utilities</a></div>
  <p class="muted" style="font-size:.85em;margin:4px 0 10px;">Upload any PDF — a rulebook, an adventure module, a player letter — and read it as a page-turning book. Nothing is converted: pages render in the browser as you turn them, each document remembers where you left off, and you can bookmark pages (B in the reader) to jump straight back to them.</p>
  <details class="sp-card" open><summary><h3>Add a PDF</h3></summary>
    <form data-api="/handouts/upload" data-multipart="1" id="handoutUpload"><div class="upload-row">
      <input type="file" name="pdf" accept="application/pdf,.pdf" required class="form-control form-control-sm">
      <input type="text" name="title" class="form-control form-control-sm" placeholder="Title (blank = file name)" maxlength="120">
      <input type="submit" class="btn btn-primary btn-sm" value="Upload" id="handoutUploadBtn">
      <span class="muted" style="font-size:.8em;">PDF only, up to ${d.max_mb} MB.</span></div></form></details>
  <details class="sp-card" open><summary><h3>Library <span class="muted" style="font-weight:normal;font-size:.75em;">— ${hs.length} document${hs.length === 1 ? '' : 's'}</span></h3></summary>
    <table id="handout-tbl"><thead><tr><th>Title</th><th>Pages</th><th>Last read</th><th>Added</th><th class="num">Size</th><th></th></tr></thead><tbody>
    ${hs.length ? hs.map(h => html`<tr class="${h.on_disk ? '' : 'missing'}" data-id="${h.id}">
      <td><span class="title-cell" title="Click to rename" data-rename="${h.id}">${h.title}</span>${h.on_disk ? '' : html`<span class="muted" style="font-size:.8em;"> (file missing on disk)</span>`}
        ${h.bookmarks.length && h.on_disk ? html`<div class="marks">${h.bookmarks.slice(0, 8).map(b => html`<a href="/handouts/${h.id}/read?page=${b.page}" title="Open at page ${b.page}">${b.label} &middot; p.${b.page}</a>`)}
          ${h.bookmarks.length > 8 ? html`<span class="more">+${h.bookmarks.length - 8} more in the reader</span>` : ''}</div>` : ''}</td>
      <td>${h.page_count ? h.page_count : '—'}</td>
      <td>${h.page_count ? `page ${h.last_page}` : html`<span class="muted">not opened yet</span>`}</td>
      <td class="muted">${(h.created_at || '').slice(0, 10)}</td><td class="num">${h.size_h}</td>
      <td class="actions">${h.on_disk ? html`<a class="btn btn-sm btn-primary" href="/handouts/${h.id}/read">&#128214; Read</a><a class="btn btn-sm btn-outline-secondary" href="${h.file_url_dl}" data-native download title="Download the PDF">&#11015;</a>` : ''}
        <input type="button" class="btn btn-sm btn-outline-danger" value="Delete" data-delete="${h.id}" data-title="${h.title}"></td></tr>`)
      : html`<tr><td colspan="6" class="muted">No handouts yet — upload a PDF above.</td></tr>`}</tbody></table></details></div>`;
}

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/handouts');
  render(outlet, page(d));
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('#handoutUpload'); if (!f) return;
    e.preventDefault();
    const b = outlet.querySelector('#handoutUploadBtn'); b.value = 'Uploading…'; b.disabled = true;
    try { const r = await api.upload('/handouts/upload', new FormData(f)); if (r.message) toast.success(r.message); ctx.reload(); }
    catch (x) { b.value = 'Upload'; b.disabled = false; }
  });
  ctx.on(outlet, 'click', async e => {
    const del = e.target.closest('[data-delete]');
    if (del) {
      if (!confirm('Delete "' + del.dataset.title + '"? The PDF file is removed from this box.')) return;
      del.disabled = true;
      try { const j = await api.post(`/handouts/${del.dataset.delete}/delete`); if (j.ok) ctx.reload(); else { del.disabled = false; alert(j.error || 'Delete failed'); } }
      catch (x) { del.disabled = false; }
      return;
    }
    const rn = e.target.closest('[data-rename]');
    if (rn) {
      const current = rn.textContent.trim();
      const next = prompt('Rename handout', current);
      if (next === null || !next.trim() || next.trim() === current) return;
      try { const j = await api.post(`/handouts/${rn.dataset.rename}/rename`, { title: next.trim() }); if (j.ok) rn.textContent = j.title; else alert(j.error || 'Rename failed'); }
      catch (x) { /* toasted */ }
    }
  });
}

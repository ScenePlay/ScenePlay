// Downloads page (templates/assets.html): everything stored on the box.
import { html, render, raw } from '../../lib/dom.js';
import { api } from '../../api.js';

export const title = 'Downloads';
const CSS = `.sp-assets table{width:100%;font-size:.85em;border-collapse:collapse}.sp-assets th,.sp-assets td{padding:4px 8px;border-bottom:1px solid var(--sp-border);vertical-align:top}.sp-assets th{text-align:left;position:sticky;top:0;background:var(--sp-surface,#fff)}.sp-assets td.num{text-align:right;white-space:nowrap}.sp-assets .muted{color:var(--sp-muted)}.sp-assets .missing td{opacity:.55}.sp-assets .toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0 8px}.sp-assets .toolbar input{max-width:280px}.sp-assets .scroll{max-height:60vh;overflow:auto}.sp-assets .sp-dl{white-space:nowrap;font-weight:600;padding:2px 10px}.sp-assets .toolbar .btn-primary{font-weight:600;padding:6px 16px;font-size:.95em}`;

function mediaCard(titleText, kind, rows, t, zipUrl) {
  return html`<details class="sp-card" open>
    <summary><h3>${titleText} <span class="muted" style="font-weight:normal;font-size:.75em;">— ${t.count} file${t.count === 1 ? '' : 's'}, ${t.bytes_h}${t.missing ? `, ${t.missing} missing on disk` : ''}</span></h3></summary>
    <div class="toolbar"><input type="search" class="form-control form-control-sm" placeholder="Filter…" data-filter="${kind}-tbl">
      ${t.count ? html`<a class="btn btn-primary" href="${zipUrl}" data-native title="All ${t.count} files as one zip (${t.bytes_h}), stored uncompressed">&#11015; Download all ${titleText.toLowerCase()} (${t.bytes_h})</a>` : ''}</div>
    <div class="scroll"><table id="${kind}-tbl"><thead><tr><th>Title</th><th>Artist</th><th>Channel</th><th>Kind</th><th>Length</th><th>Uploaded</th><th>File</th><th class="num">Size</th><th></th></tr></thead><tbody>
      ${rows.length ? rows.map(r => html`<tr class="${r.exists ? '' : 'missing'}">
        <td>${r.name}${r.display_name && r.display_name !== r.name ? html`<div class="muted" style="font-size:.85em;">${r.display_name}</div>` : ''}</td>
        <td>${r.artist}</td><td>${r.uploader}${r.origin_playlist_title ? html`<div class="muted" style="font-size:.85em;">from playlist: ${r.origin_playlist_title}</div>` : ''}</td>
        <td class="muted">${r.kind}</td><td class="num">${r.duration_h}</td><td class="num">${r.upload_date}</td>
        <td class="muted" style="word-break:break-all;">${r.file}</td><td class="num">${r.exists ? r.size_h : 'missing'}</td>
        <td class="num">${r.exists ? html`<a class="btn btn-sm btn-primary sp-dl" href="${r.download_url}" data-native title="Download this file">&#11015; Download</a>` : ''}</td></tr>`)
      : html`<tr><td colspan="9" class="muted">Nothing downloaded yet.</td></tr>`}</tbody></table></div></details>`;
}

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/library/assets');
  render(outlet, html`<style>${raw(CSS)}</style><div class="sp-page sp-assets">
    <div class="sp-page-head"><h1>Downloads</h1><a href="/utilities" style="font-size:.85em;">&larr; Utilities</a></div>
    <p class="muted" style="font-size:.85em;margin:4px 0 10px;">Everything stored on this box. Music and video are listed by the title yt-dlp reported (your typed name, then the filename, when there is none); downloads keep the exact filename stored in the database, so a file lands with the same name it has on the box. Zips are streamed, so a large library starts downloading right away.</p>
    ${mediaCard('Music', 'music', d.music, d.totals.music, d.zip_urls.music)}
    ${mediaCard('Videos', 'video', d.video, d.totals.video, d.zip_urls.video)}
    <details class="sp-card" open><summary><h3>Pictures <span class="muted" style="font-weight:normal;font-size:.75em;">— ${d.totals.pictures.count} file${d.totals.pictures.count === 1 ? '' : 's'}, ${d.totals.pictures.bytes_h}</span></h3></summary>
      <div class="toolbar"><input type="search" class="form-control form-control-sm" placeholder="Filter…" data-filter="pictures-tbl">
        ${d.totals.pictures.count ? html`<a class="btn btn-primary" href="${d.zip_urls.pictures}" data-native title="Every upload folder as one zip">&#11015; Download all pictures (${d.totals.pictures.bytes_h})</a>` : ''}</div>
      <div class="scroll"><table id="pictures-tbl"><thead><tr><th></th><th>Folder</th><th>File</th><th>Used by</th><th class="num">Size</th><th></th></tr></thead><tbody>
        ${d.pictures.length ? d.pictures.map(r => html`<tr><td><img src="/static/uploads/${r.folder}/${r.file}" alt="" loading="lazy" style="width:48px;height:32px;object-fit:cover;border-radius:3px;background:#222;"></td>
          <td>${r.folder_label}</td><td style="word-break:break-all;">${r.file}</td><td>${r.used_by}</td><td class="num">${r.size_h}</td>
          <td class="num"><a class="btn btn-sm btn-primary sp-dl" href="${r.download_url}" data-native title="Download this file">&#11015; Download</a></td></tr>`)
        : html`<tr><td colspan="6" class="muted">No uploaded pictures.</td></tr>`}</tbody></table></div></details></div>`);
  ctx.on(outlet, 'input', e => {
    const inp = e.target.closest('input[data-filter]'); if (!inp) return;
    const q = inp.value.trim().toLowerCase();
    outlet.querySelectorAll('#' + inp.dataset.filter + ' tbody tr').forEach(tr => { tr.style.display = (!q || tr.textContent.toLowerCase().includes(q)) ? '' : 'none'; });
  });
}

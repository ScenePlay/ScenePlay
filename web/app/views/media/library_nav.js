// Shared tab strip for the Library Organizer utility (templates/_library_nav.html).
// /utilities/library itself just lands on Organize.
import { html } from '../../lib/dom.js';

export function libraryNav(active) {
  const tabs = [['organize', '⚡ Organize (one click)', '/utilities/organize'], ['genres', '♫ Genres', '/utilities/genres'],
    ['artists', '👤 Artists', '/utilities/artists'], ['scenes', '🎬 Smart Scenes', '/utilities/smart-scenes']];
  return html`<div class="d-flex gap-1 flex-wrap align-items-center" style="margin:0 0 12px;border-bottom:1px solid var(--sp-border);padding-bottom:8px;">
    <span class="muted small" style="margin-right:6px;color:var(--sp-muted);">Library Organizer:</span>
    ${tabs.map(([k, label, href]) => html`<a class="btn btn-sm ${active === k ? 'btn-primary' : 'btn-outline-secondary'}" href="${href}">${label}</a>`)}
    <a href="/utilities" class="small ms-auto">&larr; Utilities</a></div>`;
}

export const title = 'Library Organizer';
export async function mount(outlet, ctx) { ctx.navigate('/utilities/organize', { replace: true }); }

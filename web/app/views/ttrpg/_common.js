// Shared TTRPG view bits: HP bars, portrait avatars, badges.
import { html, raw } from '../../lib/dom.js';

export const hpBar = (c, h = 6) => html`<div class="progress mt-1" style="height:${h}px;background:var(--sp-border);"><div class="progress-bar" style="width:${c.hp_pct}%;background:${c.hp_color};"></div></div>`;
export const avatar = (c, size = 40, radius = '50%') => c.portrait_url
  ? html`<img src="${c.portrait_url}" style="width:${size}px;height:${size}px;object-fit:cover;border-radius:${radius};" alt="">`
  : html`<div style="width:${size}px;height:${size}px;border-radius:${radius};background:var(--ttrpg-primary);display:flex;align-items:center;justify-content:center;font-size:${size > 50 ? 1.8 : 1.2}rem;color:var(--ttrpg-accent);">&#9876;</div>`;
export const statusBadge = s => s === 'active' ? raw('<span class="badge bg-success">Active</span>')
  : s === 'planning' ? raw('<span class="badge bg-warning text-dark">Planning</span>') : raw('<span class="badge bg-secondary">Ended</span>');
export const wrapIds = ids => ',' + (ids || []).join(',') + ',';

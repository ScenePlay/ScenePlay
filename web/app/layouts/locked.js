// Shown for media routes when the DM-only switch is on and the visitor is
// not a DM (the nav already hides the Tables/Utilities links).
import { html, render } from '../lib/dom.js';
export const title = 'DM only';
export async function mount(outlet, ctx) {
  render(outlet, html`<div class="sp-locked ttrpg-card p-4">
    <h3>This section is DM-only on this server</h3>
    <p class="text-muted">Log in with a DM account to use the ScenePlay controls.</p>
    <a class="btn btn-ttrpg" href="/login">Log in</a>
    <a class="btn btn-outline-secondary ms-2" href="/ttrpg">TTRPG pages</a>
  </div>`);
}

// Placeholder for views not yet ported in this phase of the FastAPI port.
import { html, render } from '../lib/dom.js';
export const title = 'Coming soon';
export async function mount(outlet, ctx) {
  render(outlet, html`<div class="sp-locked ttrpg-card p-4"><h3>Not ported yet</h3><p class="text-muted">${ctx.path}</p><a class="btn btn-outline-secondary" href="javascript:history.back()">Back</a></div>`);
}

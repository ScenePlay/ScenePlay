import { html, render } from '../lib/dom.js';
export const title = 'Not found';
export async function mount(outlet) {
  render(outlet, html`<div class="sp-locked ttrpg-card p-4"><h3>Page not found</h3><p class="text-muted">${location.pathname}</p><a class="btn btn-ttrpg" href="/">Home</a></div>`);
}

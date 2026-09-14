import { html, render } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import * as auth from '../../auth.js';
import { store } from '../../store.js';

export const title = 'First-Time Setup';

export async function mount(outlet, ctx) {
  if (!store.get('setupNeeded')) return ctx.navigate('/login', { replace: true });
  render(outlet, html`<div class="row justify-content-center mt-5"><div class="col-sm-10 col-md-6 col-lg-4"><div class="ttrpg-card p-4">
    <h3 class="text-center mb-2" style="color: var(--ttrpg-accent);">&#9876; First-Time Setup</h3>
    <p class="text-center text-muted mb-4" style="font-size:0.9em;">Create the Dungeon Master account. This page is only available until the first account is created.</p>
    <div class="alert alert-danger" id="setup-error" style="display:none"></div>
    <form id="setup-form">
      <div class="mb-3"><label class="form-label" for="su-username">DM Username</label><input id="su-username" type="text" name="username" class="form-control" autocomplete="username" autofocus required></div>
      <div class="mb-3"><label class="form-label" for="su-display">Display Name</label><input id="su-display" type="text" name="display_name" class="form-control" required></div>
      <div class="mb-3"><label class="form-label" for="su-password">Password</label><input id="su-password" type="password" name="password" class="form-control" autocomplete="new-password" required></div>
      <button type="submit" class="btn btn-ttrpg w-100">Create DM Account</button>
    </form></div></div></div>`);
  ctx.on(outlet.querySelector('#setup-form'), 'submit', async e => {
    e.preventDefault();
    const err = outlet.querySelector('#setup-error'); err.style.display = 'none';
    try {
      const res = await api.post('/api/v1/auth/setup', {
        username: outlet.querySelector('#su-username').value.trim(),
        display_name: outlet.querySelector('#su-display').value.trim(),
        password: outlet.querySelector('#su-password').value,
      }, { quiet: true, noAuth: true });
      auth.storeToken(res.token, true);
      store.set('user', res.user);
      store.set('setupNeeded', false);
      ctx.navigate('/ttrpg', { replace: true });
    } catch (x) { err.textContent = x instanceof ApiError ? x.message : 'Setup failed'; err.style.display = ''; }
  });
}

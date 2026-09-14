import { html, render, raw } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import * as auth from '../../auth.js';

export const title = 'Change Password';

export async function mount(outlet, ctx) {
  const state = { error: '', success: '' };
  const draw = () => render(outlet, html`<div class="row justify-content-center"><div class="col-md-5"><div class="ttrpg-card p-4">
    <h4 style="color: var(--ttrpg-accent);">Change Password</h4>
    ${state.error ? html`<div class="alert alert-danger">${state.error}</div>` : raw('')}
    ${state.success ? html`<div class="alert alert-success">${state.success}</div>` : raw('')}
    <form id="cp-form">
      <div class="mb-3"><label class="form-label" for="cp-cur">Current Password</label><input id="cp-cur" type="password" class="form-control" required autocomplete="current-password"></div>
      <div class="mb-3"><label class="form-label" for="cp-new">New Password</label><input id="cp-new" type="password" class="form-control" required autocomplete="new-password"></div>
      <div class="mb-3"><label class="form-label" for="cp-new2">Confirm New Password</label><input id="cp-new2" type="password" class="form-control" required autocomplete="new-password"></div>
      <button type="submit" class="btn btn-ttrpg w-100">Update Password</button>
    </form></div></div></div>`);
  draw();
  ctx.on(outlet, 'submit', async e => {
    e.preventDefault(); state.error = ''; state.success = '';
    try {
      const r = await api.post('/api/v1/auth/change-password', {
        current_password: outlet.querySelector('#cp-cur').value, new_password: outlet.querySelector('#cp-new').value, confirm_password: outlet.querySelector('#cp-new2').value,
      }, { quiet: true });
      if (r.token) { let remembered = true; try { remembered = !!localStorage.getItem('sp_jwt'); } catch (x) {} auth.storeToken(r.token, remembered); }
      state.success = r.message;
    } catch (x) { state.error = x instanceof ApiError ? x.message : String(x.message || x); }
    draw();
  });
}

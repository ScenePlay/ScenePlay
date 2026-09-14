import { html, render } from '../../lib/dom.js';
import * as auth from '../../auth.js';
import { store } from '../../store.js';
import { ApiError } from '../../api.js';

export const title = 'Login';

export async function mount(outlet, ctx) {
  if (store.get('user')) return ctx.navigate(store.isDm() ? '/' : '/ttrpg', { replace: true });
  const noUsers = store.get('setupNeeded');
  render(outlet, html`<div class="row justify-content-center mt-5"><div class="col-sm-10 col-md-6 col-lg-4"><div class="ttrpg-card p-4">
    <h3 class="text-center mb-4" style="color: var(--ttrpg-accent);">&#9876; TTRPG Login</h3>
    <div class="alert alert-danger" id="login-error" style="display:none"></div>
    <form id="login-form">
      <div class="mb-3"><label class="form-label" for="login-username">Username</label><input id="login-username" type="text" name="username" class="form-control" autocomplete="username" autofocus required></div>
      <div class="mb-3"><label class="form-label" for="login-password">Password</label><input id="login-password" type="password" name="password" class="form-control" autocomplete="current-password" required></div>
      <div class="form-check mb-3"><input class="form-check-input" type="checkbox" id="login-remember" checked><label class="form-check-label small" for="login-remember">Keep me signed in on this device</label></div>
      <button type="submit" class="btn btn-ttrpg w-100">Enter</button>
    </form>
    ${noUsers ? html`<div class="text-center mt-3"><a href="/ttrpg/setup" style="color: var(--ttrpg-accent); font-size:0.9em;">No accounts yet? Create the DM account &rarr;</a></div>`
              : html`<div class="text-center mt-3"><a href="/ttrpg/recover" class="text-muted" style="font-size:0.85em;">Forgot password? (requires access to the server)</a></div>`}
  </div></div></div>`);
  ctx.on(outlet.querySelector('#login-form'), 'submit', async e => {
    e.preventDefault();
    const err = outlet.querySelector('#login-error'); err.style.display = 'none';
    const btn = e.target.querySelector('button'); btn.disabled = true;
    try {
      const res = await auth.login(outlet.querySelector('#login-username').value.trim(), outlet.querySelector('#login-password').value, outlet.querySelector('#login-remember').checked);
      let ret = null; try { ret = sessionStorage.getItem('sp_return'); sessionStorage.removeItem('sp_return'); } catch (x) {}
      ret = ret || ctx.query.next || (res.user.role === 'dm' ? '/ttrpg' : '/ttrpg');
      ctx.navigate(ret, { replace: true });
    } catch (x) {
      err.textContent = x instanceof ApiError ? x.message : 'Login failed';
      err.style.display = '';
    } finally { btn.disabled = false; }
  });
}

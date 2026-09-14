import { html, render, raw } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import { store } from '../../store.js';

export const title = 'Password Recovery';

export async function mount(outlet, ctx) {
  if (store.get('user')) return ctx.navigate('/ttrpg', { replace: true });
  const state = { error: '', code_path: '', ttl: 15, username: '' };
  const draw = () => render(outlet, html`<div class="row justify-content-center mt-5"><div class="col-sm-10 col-md-8 col-lg-5"><div class="ttrpg-card p-4">
    <h3 class="text-center mb-2" style="color: var(--ttrpg-accent);">&#128273; Password Recovery</h3>
    <p class="small text-muted text-center mb-4">Proves you have local access to the server: a one-time code is written to a file <em>on the server's disk</em>. Open that file (console, SSH, or file browser on the box), then enter the code below.</p>
    ${state.error ? html`<div class="alert alert-danger py-2">${state.error}</div>` : raw('')}
    ${state.code_path ? html`<div class="alert alert-success py-2"><strong>Code file created.</strong> On the server, open:<br><code style="word-break:break-all;">${state.code_path}</code><br><span class="small">The code expires in ${state.ttl} minutes and is deleted after use.</span></div>` : raw('')}
    <form id="rc-gen" class="mb-4 pb-3" style="border-bottom:1px solid var(--sp-border);">
      <div class="small fw-bold text-muted mb-2" style="text-transform:uppercase;letter-spacing:.06em;">Step 1 — write a code file on the server</div>
      <div class="mb-2"><label class="form-label" for="rc-user1">Username</label><input id="rc-user1" type="text" value="${state.username}" class="form-control" autocomplete="username" required></div>
      <button type="submit" class="btn btn-outline-secondary w-100">Generate code file</button>
    </form>
    <form id="rc-reset">
      <div class="small fw-bold text-muted mb-2" style="text-transform:uppercase;letter-spacing:.06em;">Step 2 — enter the code from the file</div>
      <div class="mb-2"><label class="form-label" for="rc-user2">Username</label><input id="rc-user2" type="text" value="${state.username}" class="form-control" autocomplete="username" required></div>
      <div class="mb-2"><label class="form-label" for="rc-code">Recovery code</label><input id="rc-code" type="text" placeholder="XXXX-XXXX" class="form-control" autocomplete="one-time-code" required></div>
      <div class="mb-2"><label class="form-label" for="rc-pw">New password</label><input id="rc-pw" type="password" class="form-control" autocomplete="new-password" required></div>
      <div class="mb-3"><label class="form-label" for="rc-pw2">Confirm new password</label><input id="rc-pw2" type="password" class="form-control" autocomplete="new-password" required></div>
      <button type="submit" class="btn btn-ttrpg w-100">Reset password</button>
    </form>
    <div class="text-center mt-3"><a href="/login" style="color: var(--ttrpg-accent); font-size:0.9em;">&larr; Back to login</a></div>
  </div></div></div>`);
  draw();
  ctx.on(outlet, 'submit', async e => {
    e.preventDefault();
    state.error = '';
    try {
      if (e.target.id === 'rc-gen') {
        state.username = outlet.querySelector('#rc-user1').value.trim();
        const r = await api.post('/api/v1/auth/recover/generate', { username: state.username }, { quiet: true, noAuth: true });
        state.code_path = r.code_path; state.ttl = r.ttl;
      } else {
        state.username = outlet.querySelector('#rc-user2').value.trim();
        const r = await api.post('/api/v1/auth/recover/reset', {
          username: state.username, code: outlet.querySelector('#rc-code').value,
          new_password: outlet.querySelector('#rc-pw').value, confirm_password: outlet.querySelector('#rc-pw2').value,
        }, { quiet: true, noAuth: true });
        const { toast } = await import('../../ui/toast.js');
        toast.success(r.message);
        return ctx.navigate('/login', { replace: true });
      }
    } catch (x) { state.error = x instanceof ApiError ? x.message : String(x.message || x); }
    draw();
  });
}

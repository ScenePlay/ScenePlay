// Manage Users (DM) — templates/ttrpg/register.html.
import { html, render, raw } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import { store } from '../../store.js';
import { toast } from '../../ui/toast.js';

export const title = 'Manage Users';

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/users');
  const me = store.get('user');
  render(outlet, html`<div class="row">
    <div class="col-md-5"><div class="ttrpg-card p-4 mb-4"><h4 style="color: var(--ttrpg-accent);">Create Account</h4>
      <div class="alert alert-danger" id="u-error" style="display:none"></div>
      <form id="u-form">
        <div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Display Name</label><input type="text" name="display_name" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required autocomplete="new-password"></div>
        <div class="mb-3"><label class="form-label">Role</label><select name="role" class="form-select"><option value="player">Player</option><option value="dm">Dungeon Master</option></select></div>
        <button type="submit" class="btn btn-ttrpg w-100">Create Account</button></form></div></div>
    <div class="col-md-7"><div class="ttrpg-card p-4"><h4 style="color: var(--ttrpg-accent);">All Users</h4>
      <table class="table table-sm table-hover ttrpg-table"><thead><tr><th>Display Name</th><th>Username</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>
      ${d.users.map(u => html`<tr><td>${u.display_name}</td><td>${u.username}</td>
        <td><span class="badge ${u.role === 'dm' ? 'bg-warning text-dark' : 'bg-secondary'}">${u.role.toUpperCase()}</span></td>
        <td><span class="badge ${u.active ? 'bg-success' : 'bg-danger'}">${u.active ? 'Active' : 'Inactive'}</span></td>
        <td class="d-flex gap-2 flex-wrap"><button type="button" class="btn btn-sm btn-outline-secondary" data-edit="${u.user_id}" data-username="${u.username}" data-display="${u.display_name}">Edit</button>
          <button type="button" class="btn btn-sm btn-ttrpg" data-reset="${u.user_id}" data-display="${u.display_name}">Reset PW</button>
          ${me && u.user_id !== me.user_id ? html`<button type="button" class="btn btn-sm btn-danger" data-delete="${u.user_id}" data-display="${u.display_name}" data-role="${u.role}">Delete</button>` : ''}</td></tr>`)}</tbody></table></div></div></div>
  <div class="modal fade" id="resetPwModal" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-sm"><div class="modal-content"><div class="modal-header border-secondary"><h5 class="modal-title" style="color:var(--ttrpg-accent);">Reset Password</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <form id="resetPwForm"><div class="modal-body"><p id="resetPwLabel" class="mb-3 text-secondary"></p><div class="mb-3"><label class="form-label">New Password</label><input type="password" id="resetPwInput" class="form-control" required autocomplete="new-password"></div></div>
    <div class="modal-footer border-secondary"><button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button><button type="submit" class="btn btn-ttrpg btn-sm">Reset</button></div></form></div></div></div>
  <div class="modal fade" id="editUserModal" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-sm"><div class="modal-content"><div class="modal-header border-secondary"><h5 class="modal-title" style="color:var(--ttrpg-accent);">Edit Account</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <form id="editUserForm"><div class="modal-body"><div class="mb-3"><label class="form-label">Username <span class="text-secondary">(login)</span></label><input type="text" id="editUsernameInput" class="form-control" required><div class="form-text">They log in with the new name from their next login; nobody is logged out now.</div></div>
      <div class="mb-3"><label class="form-label">Display Name</label><input type="text" id="editDisplayInput" class="form-control" required><div class="form-text">What the stream overlays show.</div></div></div>
    <div class="modal-footer border-secondary"><button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button><button type="submit" class="btn btn-ttrpg btn-sm">Save</button></div></form></div></div></div>`);
  const $ = s => outlet.querySelector(s);
  const BS = window.bootstrap;
  let editId = null, resetId = null;
  ctx.on($('#u-form'), 'submit', async e => {
    e.preventDefault(); const f = e.target; const err = $('#u-error'); err.style.display = 'none';
    try { const r = await api.post('/api/v1/users', { username: f.username.value, display_name: f.display_name.value, password: f.password.value, role: f.role.value }, { quiet: true }); toast.success(r.message); ctx.reload(); }
    catch (x) { err.textContent = x instanceof ApiError ? x.message : String(x.message || x); err.style.display = ''; }
  });
  ctx.on(outlet, 'click', async e => {
    const ed = e.target.closest('[data-edit]'), rs = e.target.closest('[data-reset]'), dl = e.target.closest('[data-delete]');
    if (ed) { editId = ed.dataset.edit; $('#editUsernameInput').value = ed.dataset.username; $('#editDisplayInput').value = ed.dataset.display; BS.Modal.getOrCreateInstance($('#editUserModal')).show(); }
    else if (rs) { resetId = rs.dataset.reset; $('#resetPwLabel').textContent = 'Set a new password for ' + rs.dataset.display + '.'; $('#resetPwInput').value = ''; BS.Modal.getOrCreateInstance($('#resetPwModal')).show(); }
    else if (dl) { const dm = dl.dataset.role === 'dm'; if (!confirm(`Delete ${dm ? 'DM account ' : ''}${dl.dataset.display}?${dm ? ' They will lose all DM access.' : ''}`)) return; const r = await api.post(`/api/v1/users/${dl.dataset.delete}/delete`); toast.success(r.message); ctx.reload(); }
  });
  ctx.on($('#editUserForm'), 'submit', async e => { e.preventDefault(); const r = await api.post(`/api/v1/users/${editId}/edit`, { username: $('#editUsernameInput').value, display_name: $('#editDisplayInput').value }); toast.success(r.message); BS.Modal.getOrCreateInstance($('#editUserModal')).hide(); ctx.reload(); });
  ctx.on($('#resetPwForm'), 'submit', async e => { e.preventDefault(); const r = await api.post(`/api/v1/users/${resetId}/reset-password`, { new_password: $('#resetPwInput').value }); toast.success(r.message); BS.Modal.getOrCreateInstance($('#resetPwModal')).hide(); });
  ctx.cleanup(() => { outlet.querySelectorAll('.modal').forEach(m => { const inst = BS.Modal.getInstance(m); if (inst) inst.dispose(); }); document.querySelectorAll('.modal-backdrop').forEach(b => b.remove()); document.body.classList.remove('modal-open'); });
}

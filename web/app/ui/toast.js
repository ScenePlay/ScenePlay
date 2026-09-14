// Flash-message replacement: Bootstrap toasts bottom-right.
function _show(kind, text, { ms = 5000 } = {}) {
  const host = document.getElementById('sp-toasts');
  if (!host) { console.log(kind, text); return; }
  const cls = { info: 'text-bg-primary', success: 'text-bg-success', warn: 'text-bg-warning', error: 'text-bg-danger' }[kind] || 'text-bg-secondary';
  const el = document.createElement('div');
  el.className = `toast align-items-center ${cls} border-0`;
  el.setAttribute('role', 'status');
  el.innerHTML = '<div class="d-flex"><div class="toast-body"></div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
  el.querySelector('.toast-body').textContent = text;
  host.appendChild(el);
  const BS = window.bootstrap;
  if (BS && BS.Toast) {
    const t = new BS.Toast(el, { delay: ms });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    t.show();
  } else { el.classList.add('show'); setTimeout(() => el.remove(), ms); }
}

export const toast = {
  info: (t, o) => _show('info', t, o),
  success: (t, o) => _show('success', t, o),
  warn: (t, o) => _show('warn', t, o),
  error: (t, o) => _show('error', t, o),
};

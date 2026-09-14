// <form data-api="/path" data-method="POST" data-multipart data-confirm="…"
//       data-reload data-navigate="/x"> — replaces form+flash+redirect flows.
import { api, ApiError } from '../api.js';
import { toast } from '../ui/toast.js';

export function bindApiForms(root, ctx) {
  const handler = async (e) => {
    const form = e.target.closest && e.target.closest('form[data-api]');
    if (!form || !root.contains(form)) return;
    e.preventDefault();
    const confirmText = form.dataset.confirm;
    if (confirmText && !window.confirm(confirmText)) return;
    const btn = form.querySelector('[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const method = (form.dataset.method || 'POST').toUpperCase();
      let body;
      if (form.hasAttribute('data-multipart')) body = new FormData(form);
      else {
        body = {};
        for (const [k, v] of new FormData(form).entries()) {
          if (k in body) { if (!Array.isArray(body[k])) body[k] = [body[k]]; body[k].push(v); } else body[k] = v;
        }
      }
      const res = await api(method, form.dataset.api, body);
      if (res && res.message) toast.success(res.message);
      form.dispatchEvent(new CustomEvent('api:done', { detail: res, bubbles: true }));
      if (form.hasAttribute('data-reload') && ctx) ctx.reload();
      else if (form.dataset.navigate && ctx) ctx.navigate(form.dataset.navigate);
    } catch (err) {
      if (!(err instanceof ApiError)) toast.error(String(err.message || err));
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  root.addEventListener('submit', handler);
  return () => root.removeEventListener('submit', handler);
}

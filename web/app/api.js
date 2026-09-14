// fetch wrapper: JSON in/out, bearer, error envelope, 401/403 handling.
import * as auth from './auth.js';
import { store } from './store.js';
import { toast } from './ui/toast.js';

export class ApiError extends Error {
  constructor(status, message, code, detail) { super(message); this.status = status; this.code = code; this.detail = detail; }
}

async function _parse(res) {
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) { try { return await res.json(); } catch (e) { return null; } }
  return await res.text();
}

export async function api(method, path, body = null, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const tok = opts.noAuth ? null : auth.token();
  if (tok) headers.set('Authorization', 'Bearer ' + tok);
  let payload = body;
  if (body !== null && body !== undefined && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload, signal: opts.signal, cache: opts.cache || 'no-store' });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    if (!opts.quiet) toast.error('Network error — is ScenePlay running?');
    throw new ApiError(0, 'network error', 'network');
  }
  if (opts.raw) return res;
  const data = await _parse(res);
  if (res.ok) return opts.text ? data : data;
  const msg = (data && typeof data === 'object' && (data.error || data.message)) || (typeof data === 'string' && data) || res.statusText || 'error';
  const code = data && typeof data === 'object' ? data.code : null;
  const err = new ApiError(res.status, msg, code, data && data.detail);
  if (res.status === 401 && tok) { auth.expired(); throw err; }
  if (res.status === 403 && code === 'sceneplay_locked') { store.set('sceneplayLocked', true); }
  if (!opts.quiet) toast.error(msg);
  throw err;
}

api.get = (p, o) => api('GET', p, null, o);
api.post = (p, b, o) => api('POST', p, b, o);
api.del = (p, o) => api('DELETE', p, null, o);
api.upload = (p, formData, o) => api('POST', p, formData, o);

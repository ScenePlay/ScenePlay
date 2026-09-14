// Wraps window.fetch so verbatim-ported page code (303 plain fetch() calls)
// sends the bearer to same-origin endpoints and reacts to 401 like api.js.
import * as auth from '../auth.js';

let _installed = false;
export function installFetchShim() {
  if (_installed) return;
  _installed = true;
  const orig = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    let url;
    try { url = new URL(typeof input === 'string' ? input : input.url, location.href); } catch (e) { return orig(input, init); }
    if (url.origin !== location.origin) return orig(input, init);
    init = init ? { ...init } : {};
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    const tok = auth.token();
    if (tok && !headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + tok);
    init.headers = headers;
    const res = await orig(input, init);
    if (res.status === 401 && tok) auth.expired();
    return res;
  };
}

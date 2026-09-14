// Shared by the OBS browser-source pages (card, tile, panel, map). A classic
// script on purpose: these pages run inside OBS's CEF browser source with no
// ScenePlay login, so everything the old Jinja templates injected now comes
// from the query string (t, over, strip, mode, quality) or the /state poll.
window.OBS = (function () {
  const q = new URLSearchParams(location.search);
  const token = q.get('t') || '';
  const path = location.pathname.replace(/\/+$/, '');

  function el(id) { return document.getElementById(id); }
  function hpColor(p) { return p > 50 ? '#3fa14a' : p > 20 ? '#c9a227' : '#c0392b'; }

  // /ttrpg/obs/card/7 -> /ttrpg/obs/card/7/state ; a tile polls its CARD's
  // state (same numbers, same token) exactly as the Jinja poll_url did.
  function stateUrl() {
    return path.replace(/\/tile\/([^/]+)$/, '/card/$1') + '/state?t=' + encodeURIComponent(token);
  }
  // /ttrpg/obs/map -> /ttrpg/obs/map/<leaf>?t=...
  function sibling(leaf) { return path + '/' + leaf + '?t=' + encodeURIComponent(token); }

  const isHex = h => /^#[0-9a-fA-F]{6}$/.test(h || '');
  function hexRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16),
            parseInt(h.slice(5, 7), 16)];
  }
  function rgba(h, a) { const [r, g, b] = hexRgb(h); return `rgba(${r},${g},${b},${a})`; }
  function lighten(h, f) {
    const [r, g, b] = hexRgb(h).map(v => Math.round(v + (255 - v) * f));
    return `rgb(${r},${g},${b})`;
  }
  function darken(h, f) {
    const [r, g, b] = hexRgb(h).map(v => Math.round(v * (1 - f)));
    return `rgb(${r},${g},${b})`;
  }

  // 4%-alpha white fractal noise, tiled — the "dither" that keeps a gradient
  // from banding once the stream encoder gets hold of it.
  const NOISE_LAYER = 'url("data:image/svg+xml,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="140">' +
    '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2"/>' +
    '<feColorMatrix type="matrix" values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0"/></filter>' +
    '<rect width="140" height="140" filter="url(#n)"/></svg>') + '")';

  // Art may be a still OR a looping video (mp4/webm). One painter for both:
  // point the right element at the URL, hide the other. Videos autoplay
  // because they are muted — no user gesture exists inside a browser source.
  function isVideoUrl(u) { return /\.(mp4|webm)(\?|$)/i.test(u || ''); }
  function paintMedia(imgEl, vidEl, url) {
    const wantVid = isVideoUrl(url);
    const on = wantVid ? vidEl : imgEl;
    const off = wantVid ? imgEl : vidEl;
    off.removeAttribute('src');
    off.style.display = 'none';
    if (off === vidEl) { try { vidEl.pause(); } catch (e) {} }
    if (url) {
      if (on.getAttribute('src') !== url) {
        on.src = url;
        if (on === vidEl) vidEl.play().catch(() => {});
      }
      on.style.display = '';
    } else {
      on.removeAttribute('src');
      on.style.display = 'none';
    }
    return on;
  }

  // Self-scheduling, jittered poll: every tile/card in the party runs one of
  // these, so spreading them out keeps the whole table from firing on the
  // same tick. `msFn()` is asked each round so a payload-driven interval
  // (poll_s in the state, back-off while nothing changes) takes effect live.
  function poll(url, apply, msFn) {
    const tick = () => fetch(url, { cache: 'no-store' }).then(r => r.json()).then(apply).catch(() => {})
      .finally(() => setTimeout(tick, Math.max(500, msFn()) * (0.85 + Math.random() * 0.3)));
    tick();
  }

  return { q, token, el, hpColor, stateUrl, sibling, isHex, hexRgb, rgba, lighten, darken,
           NOISE_LAYER, isVideoUrl, paintMedia, poll };
})();

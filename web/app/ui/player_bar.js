// Player bar (base.html): volume | now playing | transport | queue counts | stop.
// Full wiring lands with P1 (home + media core); the shell mounts it now so
// layouts are complete.
import { html, render } from '../lib/dom.js';
import { store } from '../store.js';
import { sse } from '../sse.js';
import { api } from '../api.js';
import { fmtQueueDur } from '../lib/format.js';

let _offs = [];

function tpl(d) {
  const keep = store.get('keepMusic');
  return html`
    <div class="sp-player-section sp-player-volume">
      <h2 id="volume">Master Volume: ${d.volume}</h2>
      <input type="range" min="0" max="100" id="volume_slider" value="${d.volume}" class="sp-volume-slider">
    </div>
    <div class="sp-player-section sp-player-np">
      <div id="npScene" class="sp-np-scene"></div>
      <div id="npSong" class="sp-np-row"><img id="npSongThumb" class="sp-np-thumb" data-mtype="music" alt=""><span id="npSongText" class="sp-np-text sp-np-muted">&#9835; nothing playing</span></div>
      <div id="npVideo" class="sp-np-row"><img id="npVideoThumb" class="sp-np-thumb" data-mtype="video" alt=""><span id="npVideoText" class="sp-np-text sp-np-muted">&#9654; nothing playing</span></div>
    </div>
    <div class="sp-player-section">
      <div class="d-flex gap-2"><div class="btn-group" role="group" aria-label="Music seek and pause">
        <button type="button" id="musicBackBtn" class="btn btn-secondary">&lt;</button><button type="button" id="musicPauseButton" class="btn btn-secondary">||</button><button type="button" id="musicFwdBtn" class="btn btn-secondary">&gt;</button></div>
        <button type="button" id="nextSongBtn" class="btn btn-primary">Next Song</button></div>
      <div class="d-flex gap-2"><div class="btn-group" role="group" aria-label="Video seek and pause">
        <button type="button" id="videoBackBtn" class="btn btn-secondary">&lt;</button><button type="button" id="playPauseButton" class="btn btn-secondary">||</button><button type="button" id="videoFwdBtn" class="btn btn-secondary">&gt;</button></div>
        <button type="button" id="nextVideoBtn" class="btn btn-primary">Next Video</button></div>
    </div>
    <div class="sp-player-section"><div id="songQueueCount">Songs: 0</div><div id="videoQueueCount">Video: 0</div></div>
    <div class="sp-player-section" id="playersOffBadge" style="display:none;" title="This instance runs with SP_WORKERS=0: scene activation fills the queue but nothing plays. Start it with players (VS Code: the 'WITH players' configuration; shell: make serve / startApp)."><span class="badge text-bg-warning">Players OFF</span><div class="small" style="color:var(--sp-muted);">dev instance</div></div>
    <div class="sp-player-section">
      <div><button type="button" id="killQueueBtn" class="btn btn-danger">All Stop</button></div>
      <div><label class="sp-keep-label" for="keepMusicBtn" title="When ON, songs stay in the queue after playing and music keeps going through All Stop">Infinite Play</label><br>
        <button id="keepMusicBtn" type="button" class="btn ${keep ? 'btn-success' : 'btn-secondary'}">${keep ? 'ON' : 'OFF'}</button></div>
    </div>`;
}

function npRow(prefix, icon, item) {
  const txt = document.getElementById(prefix + 'Text'), img = document.getElementById(prefix + 'Thumb');
  if (!txt || !img) return;
  const xTimes = (item && item.loops > 0) ? ' ×' + (item.loops + 1) : '';
  txt.textContent = icon + ' ' + (item ? item.name + xTimes : 'nothing playing');
  txt.classList.toggle('sp-np-muted', !item);
  if (item && item.thumbnail && img.dataset.err !== item.thumbnail) {
    if (img.getAttribute('src') !== item.thumbnail) img.src = item.thumbnail;
    img.dataset.mid = item.id;
    img.style.display = 'block';
  } else img.style.display = 'none';
}

function applyNowPlaying(np) {
  if (!np) return;
  store.set('nowPlaying', np);
  npRow('npSong', '♫', np.song);
  npRow('npVideo', '▶', np.video);
  const s = document.getElementById('npScene'); if (s) s.textContent = np.scene ? 'Scene: ' + np.scene.name : '';
}

function applyCounts(c) {
  if (!c) return;
  if (Array.isArray(c)) { const o = {}; c.forEach(x => Object.assign(o, x)); c = o; }
  store.set('queueCounts', c);
  const sq = document.getElementById('songQueueCount'), vq = document.getElementById('videoQueueCount');
  if (sq) sq.textContent = 'Songs: ' + (c.songQCnt ?? 0) + fmtQueueDur(c.songQDur);
  if (vq) vq.textContent = 'Video: ' + (c.videoQCnt ?? 0) + fmtQueueDur(c.videoQDur);
}

export async function mountPlayerBar(el) {
  let d = { volume: 0 };
  try { d = await api.get('/api/v1/player', { quiet: true }); } catch (e) {}
  render(el, tpl(d));
  const paintWorkers = () => { const b = el.querySelector('#playersOffBadge'); if (b) b.style.display = (store.get('serverInfo') || {}).workers === false ? '' : 'none'; };
  paintWorkers(); _offs.push(store.subscribe('serverInfo', paintWorkers));
  applyNowPlaying(d.nowplaying); applyCounts(d.counts);
  const post = (p, b) => api.post(p, b || null, { quiet: true }).catch(() => {});
  const wire = (id, ev, fn) => { const n = el.querySelector('#' + id); if (n) n.addEventListener(ev, fn); };
  let volT = null;
  wire('volume_slider', 'input', e => { const v = e.target.value; el.querySelector('#volume').textContent = 'Master Volume: ' + v; clearTimeout(volT); volT = setTimeout(() => post('/set_volume', { volume: Number(v) }), 150); });
  wire('musicBackBtn', 'click', () => post('/music_seek', { value: -30 }));
  wire('musicPauseButton', 'click', () => post('/music_stopstart'));
  wire('musicFwdBtn', 'click', () => post('/music_seek', { value: 30 }));
  wire('nextSongBtn', 'click', () => post('/nextsong'));
  wire('videoBackBtn', 'click', () => post('/video_seek', { value: -30 }));
  wire('playPauseButton', 'click', () => post('/video_stopstart'));
  wire('videoFwdBtn', 'click', () => post('/video_seek', { value: 30 }));
  wire('nextVideoBtn', 'click', () => post('/nextvideo'));
  // Kill first, THEN the pseudo-scene -1 teardown (lights off on RPiLED, WLED
  // and the relay; CurrentScene cleared) — the pair the 1.x button sent.
  wire('killQueueBtn', 'click', () => post('/killqueue').then(() => post('/activatescenes/?id=-1')));
  wire('keepMusicBtn', 'click', async () => {
    const r = await api.post('/api/keepmusicplaying');
    store.set('keepMusic', !!r.keep_music);
    const b = el.querySelector('#keepMusicBtn'); b.textContent = r.keep_music ? 'ON' : 'OFF'; b.className = 'btn ' + (r.keep_music ? 'btn-success' : 'btn-secondary');
  });
  for (const id of ['npSongThumb', 'npVideoThumb']) {
    const img = el.querySelector('#' + id);
    img.addEventListener('error', () => { img.dataset.err = img.src; img.style.display = 'none'; });
    img.addEventListener('click', () => { if (window.showMediaMeta) window.showMediaMeta(img.dataset.mtype, img.dataset.mid); });
  }
  _offs.push(sse.subscribe('nowplaying', applyNowPlaying, { fallback: { every: 4000, fetch: () => api.get('/api/nowplaying', { quiet: true }) } }));
  _offs.push(sse.subscribe('queue', applyCounts, { fallback: { every: 5000, fetch: () => api.get('/api/songandvideocount', { quiet: true }) } }));
}

export function unmountPlayerBar() { for (const o of _offs.splice(0)) o(); }

// Sync progress toast (base_ttrpg.html's startSync/_pollSync) for the library
// pages: the syncjob:<job> SSE topic drives it, the old /sync/status poll is
// the fallback. The toast host (#sync-toast) lives in layouts/ttrpg.js.
import { api } from '../../../api.js';

const $ = id => document.getElementById(id);

function _els() {
  return { toast: $('sync-toast'), title: $('sync-toast-title'), bar: $('sync-toast-bar'), pct: $('sync-toast-pct'), lbl: $('sync-toast-label') };
}

export function hideSyncToast() { const t = $('sync-toast'); if (t) t.style.display = 'none'; }

// Follow one running job until it finishes; resolves with the final state.
export function watchSync(ctx, job, statusUrl, onState) {
  return new Promise(resolve => {
    let done = false, off = null, poll = null;
    const apply = s => {
      if (done || !s) return;
      onState(s);
      if (!s.running) { done = true; if (off) off(); if (poll) clearInterval(poll); resolve(s); }
    };
    off = ctx.subscribe('syncjob:' + job, apply, { fallback: { every: 700, fetch: () => api.get(statusUrl, { quiet: true }) } });
    // belt and braces: a job that finishes before the SSE stream (re)connects
    poll = ctx.every(2500, () => api.get(statusUrl, { quiet: true }).then(apply).catch(() => {}));
    ctx.cleanup(() => { done = true; });
  });
}

export async function startSync(ctx, job, syncUrl, statusUrl, { onDone } = {}) {
  const { toast, title, bar, pct, lbl } = _els();
  const btn = $('sync-btn-' + job);
  if (!toast) return;
  bar.style.width = '5%';
  bar.style.background = 'var(--ttrpg-accent)';
  pct.textContent = '0%';
  lbl.textContent = 'Fetching list from API…';
  title.textContent = '↻ Syncing ' + job.charAt(0).toUpperCase() + job.slice(1) + '…';
  toast.style.display = '';
  if (btn) { btn.disabled = true; btn.textContent = '↻ Running…'; }
  let data;
  try { data = await api.post(syncUrl, null, { quiet: true }); }
  catch (e) { lbl.textContent = '✗ ' + (e.message || 'Network error'); if (btn) btn.disabled = false; return; }
  if (data.error) { lbl.textContent = '✗ ' + data.error; if (btn) btn.disabled = false; return; }
  const s = await watchSync(ctx, job, statusUrl, st => {
    const total = st.total || 0, done = st.done || 0;
    const p = total > 0 ? Math.round(done / total * 100) : (st.running ? 8 : 100);
    bar.style.width = p + '%'; pct.textContent = p + '%';
    if (st.running) lbl.textContent = total > 0 ? 'Processing ' + done + ' / ' + total + '…' : 'Fetching list from API…';
  });
  bar.style.width = '100%'; pct.textContent = '100%'; bar.style.background = '#28a745';
  title.textContent = '✓ Sync Complete';
  lbl.textContent = s.message || 'Done.';
  if (btn) { btn.disabled = false; btn.innerHTML = '&#8635; Sync SRD'; }
  ctx.after(2500, () => { hideSyncToast(); if (onDone) onDone(s); else ctx.reload(); });
}

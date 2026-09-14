// My Camera (templates/ttrpg/obs_my_feed.html): a player's — or the DM's —
// vdo.ninja push link and QR, from GET /api/v1/obs/feed/<id|dm>. The one form
// (regenerate) posts to the verbatim /ttrpg/obs/feed/<id|dm> path.
import { html, raw, render } from '../../lib/dom.js';
import { api, ApiError } from '../../api.js';
import { toast } from '../../ui/toast.js';
import { exposeGlobals } from '../../lib/legacy.js';

export const title = 'My Camera';

const INPUT = 'background:var(--ttrpg-surface);color:var(--ttrpg-text);border-color:var(--sp-border);';

function copyField(id, btn, label) {
  const f = document.getElementById(id);
  const done = () => { const t = btn.textContent; btn.textContent = label; setTimeout(() => { btn.textContent = t; }, 1500); };
  // The clipboard API needs a secure context, and the GM often runs this over
  // plain http on the LAN — fall back rather than silently fail.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(f.value).then(done, () => { f.select(); document.execCommand('copy'); done(); });
  } else {
    f.select(); f.setSelectionRange(0, 99999); document.execCommand('copy'); done();
  }
}

function view(d) {
  const kind = d.is_dm_tile ? 'DM Camera' : 'My Camera';
  return html`<div class="row justify-content-center"><div class="col-lg-7">
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 style="color:var(--ttrpg-accent);" class="mb-0">&#128247; ${kind} &mdash; ${d.char.name}</h4>
      <a href="${d.back_url}" class="btn btn-sm btn-outline-secondary">Back</a>
    </div>

    ${d.push_url ? html`<div class="ttrpg-card p-3 mb-3">
      <p class="small text-muted mb-3">
        Start your camera and you'll appear on the stream${d.is_dm_tile ? '' : ' when the GM puts you on screen'}. Nothing to install &mdash; it runs in your browser.
        <b>Phone camera?</b> Scan the code below instead of typing the link.
      </p>
      <div class="d-flex flex-wrap gap-3 align-items-start">
        ${d.qr_svg ? html`<div style="background:#fff;padding:8px;border-radius:8px;line-height:0;flex:0 0 auto;"><div style="width:190px;height:190px;">${raw(d.qr_svg)}</div></div>` : ''}
        <div class="flex-grow-1" style="min-width:15rem;">
          <!-- Top-level link, NEVER an iframe: the camera prompt needs a secure
               context and this page is usually plain LAN http. -->
          <a href="${d.push_url}" target="_blank" rel="noopener" data-native class="btn btn-ttrpg w-100 mb-2">&#128247; Start My Camera</a>
          <p class="small text-muted mb-2">Opens vdo.ninja in a new tab. Allow camera and microphone when asked, then leave that tab open for the session.</p>
          <label class="form-label small text-muted mb-1">Or copy this link to another device</label>
          <div class="d-flex gap-2">
            <input id="feed-push-url" class="form-control form-control-sm" readonly value="${d.push_url}" style="${INPUT}">
            <button class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="feedCopy(this)">Copy</button>
          </div>
          <p class="small text-muted mt-2 mb-0">&#128274; Treat this link like a password &mdash; anyone with it can watch your camera. Don't post it in chat.</p>
        </div>
      </div>
    </div>` : ''}

    ${d.is_dm && d.portal_url ? html`<div class="ttrpg-card p-3 mb-3">
      <h6 style="color:var(--ttrpg-accent);" class="mb-2">&#128279; Send this to ${d.char.name} if they're playing remotely</h6>
      <p class="small text-muted mb-2">
        This page is on your machine, so ${d.char.name} can't open it. Send them the player portal instead &mdash; once they log in${d.player_username ? html` as <code>${d.player_username}</code>` : ''}, their camera link is waiting for them under <b>My Camera</b>, and it is the same link shown above.
      </p>
      <div class="d-flex align-items-start gap-3 flex-wrap">
        ${d.portal_qr ? html`<div class="text-center"><div style="width:150px;height:150px;">${raw(d.portal_qr)}</div><div class="small text-muted mt-1">Scan to open</div></div>` : ''}
        <div class="flex-grow-1" style="min-width:16rem;">
          <div class="input-group input-group-sm mb-2">
            <input type="text" class="form-control" id="portal-link" readonly value="${d.portal_url}">
            <button class="btn btn-outline-secondary" type="button" onclick="copyPortal(this)">Copy</button>
          </div>
          <a href="${d.portal_url}" target="_blank" rel="noopener" data-native class="btn btn-sm btn-outline-secondary">Open the portal &#8599;</a>
        </div>
      </div>
    </div>` : ''}

    <div class="ttrpg-card p-3 mb-3">
      <h6 style="color:var(--ttrpg-accent);" class="mb-2">Using your own setup?</h6>
      <p class="small text-muted mb-0">
        Use the link above &mdash; it is the only one that works. ScenePlay builds it with the table's <b>room</b> baked in, which is what lets you hear everyone and lets them hear you. A link from anywhere else has no room in it, so you would publish on your own: your camera would look fine to you, you would hear nobody, and your tile would sit black on the stream with nothing to explain why.
      </p>
    </div>

    <div class="ttrpg-card p-3">
      <h6 style="color:var(--ttrpg-accent);" class="mb-2">Trouble?</h6>
      <form method="post" action="${d.save_url}" id="feed-regen-form">
        <input type="hidden" name="action" value="regenerate">
        <button class="btn btn-sm btn-outline-danger">Generate a new link</button>
        <span class="small text-muted ms-2">Use this if you shared the link by mistake, or someone else is on your feed.</span>
      </form>
      ${d.is_dm && d.view_url ? html`<hr style="border-color:var(--sp-border);">
      <label class="form-label small text-muted mb-1">GM only &mdash; the URL OBS loads for this player</label>
      <input class="form-control form-control-sm" readonly value="${d.view_url}" style="${INPUT}font-size:.75rem;">` : ''}
    </div>
  </div></div>`;
}

export async function mount(outlet, ctx) {
  const id = ctx.params.id;
  let d;
  try { d = await api.get(`/api/v1/obs/feed/${id}`, { quiet: true }); }
  catch (e) {
    if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
      toast.error(e.status === 403 ? "That camera page belongs to someone else's character." : 'No such character.');
      return ctx.navigate('/ttrpg/my-character', { replace: true });
    }
    throw e;
  }
  document.title = `${d.is_dm_tile ? 'DM Camera' : 'My Camera'} — ${d.char.name} — ScenePlay`;
  render(outlet, view(d));
  const names = exposeGlobals({
    feedCopy: btn => copyField('feed-push-url', btn, 'Copied!'),
    copyPortal: btn => copyField('portal-link', btn, 'Copied'),
  });
  ctx.cleanup(() => names());
  ctx.on(outlet, 'submit', async e => {
    const f = e.target.closest('#feed-regen-form'); if (!f) return;
    e.preventDefault();
    if (!confirm('Generate a new camera link? Your current one stops working immediately.')) return;
    const btn = f.querySelector('button'); btn.disabled = true;
    try {
      const r = await api.post(d.save_url, Object.fromEntries(new FormData(f).entries()));
      if (r && r.message) toast.success(r.message);
      ctx.reload();
    } catch (x) { btn.disabled = false; }
  });
}

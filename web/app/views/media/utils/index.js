// Utilities page (templates/utils.html): cards for YouTube import, software
// update, backup & restore, import, this server, access control, lighting,
// AI settings, download queue + chimes, downloads, handouts, extensions.
import { html, render, raw, esc } from '../../../lib/dom.js';
import { api, ApiError } from '../../../api.js';
import { toast } from '../../../ui/toast.js';
import { store } from '../../../store.js';

export const title = 'Utilities';

function card(title, body, id = '') { return html`<details class="sp-card" ${id ? raw(`id="${id}"`) : ''}><summary><h3>${title}</h3></summary>${body}</details>`; }

function page(d) {
  const isDm = d.is_dm;
  const loginLink = html`<a href="/login?next=/utilities">Log in with a DM account</a>`;
  return html`<div class="sp-page"><div class="sp-page-head"><h1>Utilities</h1></div><div>
  ${card('Youtube Import', html`
    <form id="yt-form" data-api="/api/v1/youtube/import" data-method="POST">
      <input type="text" placeholder="Video or Playlist URL" name="URLLink" class="form-control mb-3" required>
      <input type="text" placeholder="Optional display name — blank uses video metadata" name="FileName" class="form-control mb-3">
      <div class="sp-filter-row">
        <label for="mediaType">Choose Media</label>
        <select name="Media" id="mediaType" class="form-select"><optgroup label="Music"><option value="mp3">MP3</option></optgroup><optgroup label="Video"><option value="mp4">MP4</option></optgroup></select>
        <label for="sceneType">Choose Scene</label>
        <select name="Scene" id="sceneType" class="form-select">${d.scenes.map(s => html`<option value="${s[0]}">${s[1]}</option>`)}</select>
      </div>
      <button type="submit" class="btn btn-primary">Process Youtube</button></form>
    <br><label>Look up missing video details (video id, title) for rows already in the media tables:</label>
    <button type="button" class="btn btn-secondary" data-action="/api/v1/library/backfill-metadata">Backfill Metadata</button>
    <br><br><label>Check every media row for its file on disk, and re-download any that are missing:</label>
    <button type="button" class="btn btn-secondary" data-action="/api/v1/library/scan-media">Scan Media Files</button><br><br>`)}
  ${card('Software Update', html`
    <p style="font-size:.85em;color:var(--sp-muted);margin:6px 0 2px;">Before updating:</p>
    <ol style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px 22px;"><li>Create a backup (Backup &amp; Restore, below).</li><li><b>Download it to another computer.</b></li></ol>
    <p style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px;">The updater also takes its own safety backup, but that copy stays on this machine — an off-machine copy is safer.</p>
    <p id="update-status" style="font-size:.9em;margin:6px 0;">Checking for updates&hellip;</p>
    <ul id="update-list" style="font-size:.85em;margin:4px 0 8px 18px;display:none;"></ul>
    <div id="update-sudo-row" style="display:none;margin:6px 0;"><label for="update-sudo" style="font-size:.85em;display:block;margin-bottom:2px;"><b>System (sudo) password — optional.</b> Only one server-setup step needs it (the nginx upload-size fix). Leave it blank and that step is skipped — the update itself still runs. The password is used once and never stored.</label>
      <input type="password" id="update-sudo" autocomplete="new-password" class="form-control" placeholder="sudo password (optional)" style="max-width:260px;"></div>
    <input type="button" id="update-btn" class="btn btn-primary" value="Update Now" style="display:none;">
    <pre id="update-log" style="display:none;font-size:.78em;white-space:pre-wrap;background:#111;color:#ddd;padding:8px;border-radius:8px;max-height:260px;overflow:auto;margin-top:8px;"></pre>`)}
  ${card('Backup & Restore', html`
    <button type="button" class="btn btn-primary" data-action="/api/v1/backup/run">Create Backup</button>
    <button type="button" class="btn btn-secondary" id="backup-auto-btn">${d.backup_auto ? 'Disable Nightly Backup' : 'Enable Nightly Backup'}</button>
    <span style="font-size:.85em;color:var(--sp-muted);">Nightly backup is ${d.backup_auto ? 'ON — keeps the last 7 automatic snapshots' : 'off'}.</span>
    ${d.backups.length ? html`<table style="margin:8px 0;font-size:.9em;">${d.backups.map(b => html`<tr>
        <td style="border:none;padding-right:12px;"><a href="${b.url}" data-native download>${b.name}</a></td>
        <td style="border:none;padding-right:12px;color:var(--sp-muted);">${b.created}</td>
        <td style="border:none;padding-right:12px;color:var(--sp-muted);">${(b.size / 1048576).toFixed(1)} MB</td>
        <td style="border:none;"><input type="button" class="btn btn-outline-danger btn-sm" value="Delete" data-delete-backup="${b.name}"></td></tr>`)}</table>`
      : html`<p style="font-size:.85em;color:var(--sp-muted);margin:6px 0;">No backups yet.</p>`}
    <hr style="margin:8px 0;">
    <label style="display:block;font-size:.9em;margin-bottom:2px;"><b>Extra media folders.</b> When a backup is restored or merged, ScenePlay first looks for the media files on this computer before downloading them from YouTube. It always checks <code>~/Music</code> and <code>~/Videos</code> — list any additional folders to search here.</label>
    <ul style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px 18px;"><li>Separate folders with a semicolon (<code>;</code>).</li><li>Folders are searched including everything inside them, so point at media folders — not whole drives.</li></ul>
    <input type="text" id="media-roots" value="${d.media_roots}" class="form-control d-inline-block mb-2" placeholder="/mnt/media/Music;/mnt/media/Videos" style="width:70%;">
    <button type="button" class="btn btn-secondary" id="media-roots-save">Save Media Folders</button>`)}
  ${card('Import Backup', html`
    <form id="import-form">
      <input type="file" name="backupFile" accept=".zip" required class="form-control mb-2" style="max-width:420px;"><br>
      <label style="display:inline-block;margin:6px 12px 2px 0;"><input type="radio" name="mode" value="merge" checked> <b>Merge</b> — add the backup's content to this server.</label>
      <ul style="font-size:.85em;color:var(--sp-muted);margin:0 0 6px 42px;"><li>Imports campaigns, scenes, media, and homebrew library entries.</li><li>Anything this server already has is skipped (matched by video id or name).</li></ul>
      <label style="display:inline-block;margin:0 12px 2px 24px;"><input type="checkbox" name="full_merge" value="1"> <b>Full merge</b> — also import the TTRPG world.</label>
      <ul style="font-size:.85em;color:var(--sp-muted);margin:0 0 6px 66px;"><li>Adds characters, sessions, battle maps, monsters, tokens, notes, and scene lighting.</li><li>Sessions and maps with the same name are combined.</li><li>A character that already exists here (same owner and name) is kept as-is.</li><li>Imported characters whose player has no account here are placed under your account.</li><li>Play history (dice rolls, played counts) is never imported.</li></ul>
      <label style="display:inline-block;margin:0 12px 2px 0;"><input type="radio" name="mode" value="replace"> <b>Replace</b> — restore the entire database from this backup.</label>
      <ul style="font-size:.85em;color:var(--sp-muted);margin:0 0 6px 42px;"><li>Everything currently on this server is replaced.</li><li>A safety snapshot of the current data is taken first.</li></ul>
      <label style="display:inline-block;margin:0 12px 2px 0;"><input type="checkbox" name="db_only" value="1"> <b>Database only</b> — skip images and uploads.</label>
      <ul style="font-size:.85em;color:var(--sp-muted);margin:0 0 6px 42px;"><li>Use on low-memory machines (like a Pi Zero), where unpacking a large media folder can crash the restore.</li><li>If you need the images, copy the <code>static/uploads</code> folder over separately.</li></ul>
      <br><button type="submit" class="btn btn-primary">Import</button></form>`)}
  ${card('This Server', html`
    <p style="font-size:.85em;margin:6px 0;" title="Server = this computer since its last boot; ScenePlay = the app since its last start (resets on Update or a watchdog restart)">
      <b>Server up</b> ${d.uptime ? d.uptime.server_uptime : '?'} <span style="color:var(--sp-muted);">(since ${d.uptime ? d.uptime.server_boot : '?'})</span>
      &nbsp;&middot;&nbsp; <b>ScenePlay up</b> ${d.uptime ? d.uptime.app_uptime : '?'} <span style="color:var(--sp-muted);">(since ${d.uptime ? d.uptime.app_started : '?'})</span></p>
    <button type="button" class="btn btn-secondary" data-action="/api/v1/system/reset-ytdlp" data-confirm="Delete the yt-dlp checkout and re-clone it fresh from GitHub? Use this when downloads misbehave and a normal update has not helped. May take a minute." title="Delete the yt-dlp checkout and re-clone it fresh from GitHub">Reset yt-dlp</button>
    <span style="font-size:.85em;color:var(--sp-muted);">Re-downloads the yt-dlp source used for YouTube imports.</span><br><br>
    <div style="margin:6px 0;"><label for="restart-sudo" style="font-size:.85em;display:block;margin-bottom:2px;"><b>System (sudo) password — optional.</b> Needed only when this box's sudo prompts for a password; leave blank if reboots already work. Used once and never stored.</label>
      <input type="password" id="restart-sudo" autocomplete="new-password" class="form-control" placeholder="sudo password (optional)" style="max-width:260px;"></div>
    <button type="button" class="btn btn-danger" id="restart-computer" title="Requires a DM login">Restart Computer</button><br><br>`)}
  ${card('Access Control', html`
    <p style="font-size:.85em;color:var(--sp-muted);margin:6px 0;">Controls who can open the ScenePlay pages: the playback controls, the campaign / scene / media tables, and this Utilities page. The TTRPG player pages are never restricted.</p>
    ${isDm ? html`<label style="display:block;margin:6px 0;"><input type="checkbox" id="dm-only" ${d.dm_only_sceneplay ? 'checked' : ''}> <b>DM-only ScenePlay</b> — only DM logins can use the ScenePlay controls and tables.</label>`
           : html`<p style="margin:6px 0;">Currently: <b>${d.dm_only_sceneplay ? 'DM-only' : 'open to everyone on the network'}</b>. ${loginLink} to change this setting.</p>`}
    <ul style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px 18px;"><li>Anyone else who tries is sent to the login page, and the ScenePlay menu links are hidden for them.</li><li>Scene activation from TTRPG sessions, scheduled (cron) scenes, and the browser extension keep working.</li><li>Changing this setting requires a DM login.</li></ul>`)}
  ${card('Lighting', html`
    <label style="display:block;margin:6px 0;"><input type="checkbox" id="lights-off-end" ${d.lights_off_on_end ? 'checked' : ''}> <b>Lights off when a scene's media finishes</b> — once the scene's last song and video have played, the RPiLED strip, Remote boxes, WLED controllers and remote players' lights all go dark.</label>
    <ul style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px 18px;"><li>Scenes with no music or video are never affected — their lights run until the next scene or All Stop.</li><li>With Infinite Play on, the music queue never drains, so the lights stay on for as long as it plays.</li></ul>`)}
  ${card('AI Generation (optional)', isDm ? html`
    <p style="font-size:.85em;color:var(--sp-muted);margin:6px 0;">With a Google Gemini API key, every AI prompt in the battle-map tools gains a one-click <b>&#10024; Generate</b> button — map layouts, traced floorplans, map art, live video maps (Veo), textures, portraits and monster icons. The key is stored only on this machine and never enters the database, backups, git, or the relay.</p>
    <form id="ai-form" autocomplete="off">
    <p style="margin:6px 0;">Status: ${d.gemini_configured ? html`<b style="color:var(--sp-ok, #3c9a5f);">key set</b> ${d.gemini_key_source === 'env' ? '(from GEMINI_API_KEY env var — the field below is ignored)' : ''}` : html`<b style="color:var(--sp-muted);">no key</b> — get one free at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a>`}</p>
    <label style="display:block;font-size:.9em;margin-bottom:2px;"><b>API key</b></label>
    <input type="password" name="gemini_api_key" value="" autocomplete="new-password" class="form-control d-inline-block mb-2" placeholder="${d.gemini_configured ? 'leave blank to keep existing' : 'paste your Gemini API key'}" style="width:70%;">
    ${d.gemini_configured && d.gemini_key_source !== 'env' ? html`<label style="display:block;font-size:.85em;margin:2px 0 6px;"><input type="checkbox" name="gemini_clear_key" value="1"> Remove the stored key (turns the &#10024; buttons off)</label>` : ''}
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin:6px 0;">${[['text', 'Layouts (text/JSON)'], ['image', 'Images'], ['video', 'Video (Veo)']].map(([m, label]) => html`<label style="font-size:.85em;"><b>${label}</b><br><select name="gemini_model_${m}" class="form-select form-select-sm" style="width:auto;">${d.gemini_choices[m].map(x => html`<option value="${x}" ${x === d.gemini_models[m] ? 'selected' : ''}>${x}</option>`)}</select></label>`)}</div>
    <hr style="border-color:var(--sp-border);margin:10px 0;">
    <p style="font-size:.9em;margin:6px 0;"><b>Image provider</b> &mdash; which service paints the images (map art, textures, portraits, monster icons). Layouts and Veo video always use Gemini.</p>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin:4px 0;font-size:.9em;"><label><input type="radio" name="image_provider" value="gemini" ${d.image_provider !== 'runware' ? 'checked' : ''}> Google Gemini</label><label><input type="radio" name="image_provider" value="runware" ${d.image_provider === 'runware' ? 'checked' : ''}> Runware.ai (FLUX &mdash; fast, fractions of a cent per image)</label></div>
    <p style="margin:6px 0;font-size:.9em;">Runware status: ${d.runware_configured ? html`<b style="color:var(--sp-ok, #3c9a5f);">key set</b> ${d.runware_key_source === 'env' ? '(from RUNWARE_API_KEY env var — the field below is ignored)' : ''}` : html`<b style="color:var(--sp-muted);">no key</b> &mdash; create one at <a href="https://my.runware.ai/" target="_blank" rel="noopener">my.runware.ai</a>`}</p>
    <input type="password" name="runware_api_key" value="" autocomplete="new-password" class="form-control d-inline-block mb-2" placeholder="${d.runware_configured ? 'leave blank to keep existing' : 'paste your Runware API key'}" style="width:70%;">
    ${d.runware_configured && d.runware_key_source !== 'env' ? html`<label style="display:block;font-size:.85em;margin:2px 0 6px;"><input type="checkbox" name="runware_clear_key" value="1"> Remove the stored Runware key</label>` : ''}
    <p style="font-size:.9em;margin:10px 0 4px;"><b>Layout designer</b> &mdash; which service DESIGNS and traces the battle-map floorplans (the schematic step). Runware runs it through any LLM it hosts, billed to your Runware balance.</p>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin:4px 0;font-size:.9em;"><label><input type="radio" name="text_provider" value="gemini" ${d.text_provider !== 'runware' ? 'checked' : ''}> Google Gemini (direct)</label><label><input type="radio" name="text_provider" value="runware" ${d.text_provider === 'runware' ? 'checked' : ''}> Runware.ai</label></div>
    <label style="font-size:.85em;display:block;margin:4px 0;"><b>Runware layout model</b><input type="text" name="runware_text_model" value="${d.runware_text_model}" class="form-control form-control-sm" style="width:60%;"><span style="color:var(--sp-muted);">e.g. <code>google-gemini-3-5-flash</code>, <code>anthropic-claude-sonnet-4-6</code>, <code>openai-gpt-5-5</code> — tracing a map image needs a vision-capable model.</span></label>
    <label style="font-size:.85em;display:block;margin:4px 0;"><b>Runware model</b> (AIR id)<input type="text" name="runware_model" value="${d.runware_model}" class="form-control form-control-sm" style="width:60%;"><span style="color:var(--sp-muted);">e.g. <code>runware:400@3</code> = FLUX.2 klein, <code>runware:101@1</code> = FLUX.1 Dev, <code>google:4@3</code> = Nano Banana 2 (Gemini image via Runware); any Runware or CivitAI image-model AIR id works.</span></label>
    <ul style="font-size:.85em;color:var(--sp-muted);margin:2px 0 6px 18px;"><li>Gemini images cost a few cents; Runware images cost fractions of a cent; a Veo video clip costs a few dollars and takes 1&ndash;6 minutes.</li><li>The defaults are the proven models; the newer ones are offered to try &mdash; if the provider rejects one, the error says so and you can switch back here.</li></ul>
    <button type="submit" class="btn btn-secondary">Save AI Settings</button></form>` : html`<p style="margin:6px 0;">${loginLink} to configure AI generation.</p>`)}
  ${card('Download Queue', html`
    <p style="font-size:.85em;margin:6px 0;">What the YouTube downloader is doing right now, why anything failed, and the chimes it plays. Updates live while this card is open.</p>
    <div class="d-flex gap-4 flex-wrap" style="font-size:.9em;margin:6px 0 10px;">
      <div><b>Songs</b> — <span id="dlq-music-remaining">…</span> left <span class="text-muted">(<span id="dlq-music-detail"></span>)</span><br>failure rate <b id="dlq-music-rate">…</b></div>
      <div><b>Videos</b> — <span id="dlq-video-remaining">…</span> left <span class="text-muted">(<span id="dlq-video-detail"></span>)</span><br>failure rate <b id="dlq-video-rate">…</b></div></div>
    <div style="font-size:.85em;margin-bottom:10px;"><b>Chimes</b>
      <table id="chime-table" style="border-collapse:collapse;margin:4px 0;"><tbody><tr><td class="text-muted">Loading…</td></tr></tbody></table>
      <div class="d-flex gap-2 align-items-center flex-wrap" style="margin-top:4px;"><input type="file" id="chime-upload" accept=".mp3,.wav,.ogg,audio/*" class="form-control form-control-sm" style="max-width:260px;"><button type="button" class="btn btn-sm btn-outline-secondary" id="chime-upload-btn" title="Add a sound to the effects folder — it then appears in every chime's picker">&#11014; Add sound</button><span id="chime-msg" class="small text-muted"></span></div></div>
    <div class="d-flex gap-2 align-items-center flex-wrap" style="margin-bottom:6px;"><b style="font-size:.9em;">Failed downloads <span id="dlq-failed-count" class="text-muted"></span></b>
      <button type="button" class="btn btn-sm btn-primary" id="dlq-retry-all" data-dlq-retry="all" title="Put every FAILED download back in the queue">&#8635; Retry all failed</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-dlq-retry="all-unavailable" title="Also retry the rows marked Unavailable">&#8635; Retry unavailable too</button>
      <button type="button" class="btn btn-sm btn-outline-danger" id="dlq-delete-all" data-dlq-delete="all" title="Remove every FAILED download record entirely">&#10005; Delete all failed</button>
      <button type="button" class="btn btn-sm btn-outline-danger" data-dlq-delete="all-unavailable" title="Also remove the rows marked Unavailable">&#10005; Delete unavailable too</button>
      <span id="dlq-msg" class="small text-muted"></span></div>
    <div style="max-height:40vh;overflow:auto;"><table style="width:100%;font-size:.82em;border-collapse:collapse;" id="dlq-table"><thead><tr><th style="text-align:left;padding:3px 6px;">Type</th><th style="text-align:left;padding:3px 6px;">Name</th><th style="text-align:left;padding:3px 6px;">Status</th><th style="text-align:left;padding:3px 6px;">Why it failed</th><th></th></tr></thead><tbody><tr><td colspan="5" class="text-muted" style="padding:4px 6px;">Loading…</td></tr></tbody></table></div>`, 'dlq-card')}
  ${card('Downloads', html`<p style="font-size:.85em;margin:6px 0;">Pull the box's media off it: every downloaded song and video (listed by its YouTube title, with length and size) and every uploaded picture (map art, portraits, monsters, OBS cards, textures) — one file at a time, or a whole category as a zip. Backups deliberately leave media out; this is how you copy it.</p><a class="btn btn-sm btn-outline-secondary" href="/utilities/assets">Open Downloads</a>`)}
  ${card('Handouts', html`<p style="font-size:.85em;color:var(--sp-muted);margin:6px 0;">Upload any PDF — rulebooks, adventure modules, player letters — and read it as a page-turning book. Pages render in the browser as you turn them, and each document remembers where you left off.</p><a class="btn btn-sm btn-outline-secondary" href="/handouts">Open Handouts</a>`)}
  ${card('Browser Extensions', html`
    <p style="font-size:.85em;margin:6px 0;">The extension is the easiest way to get media off youtube.com. While you're on a video or playlist page, click the ScenePlay icon and hit Send — the page you're watching goes straight to this server as an MP3 or MP4. The popup remembers your server, format, and scene, so after the first setup each new video is a single click.</p>
    <a href="/static/ext/ScenePlay-firefox-signed.xpi" data-native><b>ScenePlay for Firefox (signed)</b></a> &nbsp;|&nbsp; <a href="/static/ext/ScenePlay-chrome.zip" data-native>ScenePlay-chrome.zip</a> &nbsp;|&nbsp; <a href="/static/ext/ScenePlay-firefox.xpi" data-native>firefox .xpi (unsigned, dev)</a>
    <div style="font-size:.85em;margin:6px 0;"><p style="margin:6px 0 2px;"><b>Firefox</b> (use the signed link above):</p><ul style="margin:2px 0 6px 18px;"><li>Click the link. Firefox will offer to install the extension.</li><li>If no install prompt appears, allow this site to install add-ons when Firefox asks. Or download the file and drag it onto the <code>about:addons</code> page.</li><li>This build is Mozilla-signed. It works on regular Firefox and stays installed.</li></ul>
    <p style="margin:6px 0 2px;"><b>Chrome:</b></p><ul style="margin:2px 0 6px 18px;"><li>Download <code>ScenePlay-chrome.zip</code> and unzip it.</li><li>Open <code>chrome://extensions</code> and turn on Developer mode.</li><li>Click "Load unpacked" and pick the unzipped folder.</li></ul>
    <p style="margin:6px 0 2px;"><b>Firefox dev build (unsigned)</b> — only if you know you need it:</p><ul style="margin:2px 0 6px 18px;"><li>Installs only on Firefox ESR, Developer Edition, or Nightly.</li><li>First set <code>xpinstall.signatures.required</code> to <code>false</code> in <code>about:config</code>.</li></ul>
    <p style="margin:6px 0;">Saved settings (server URL, scene) survive reinstalls in every case.</p></div>`)}
  </div></div>`;
}

export async function mount(outlet, ctx) {
  const d = await api.get('/api/v1/utilities');
  render(outlet, page(d));
  const $ = s => outlet.querySelector(s);
  const act = async (path, body, opts) => { const r = await api.post(path, body || null, opts); if (r && r.message) toast.success(r.message); return r; };

  // card open/closed memory
  outlet.querySelectorAll('details').forEach(el => {
    const key = 'sp-utils-card:' + el.querySelector('summary').textContent.trim();
    try { if (localStorage.getItem(key) === '1') el.open = true; } catch (e) {}
    ctx.on(el, 'toggle', () => { try { localStorage.setItem(key, el.open ? '1' : '0'); } catch (e) {} });
  });

  // plain action buttons
  ctx.on(outlet, 'click', async e => {
    const b = e.target.closest('button[data-action]');
    if (b) {
      if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
      b.disabled = true;
      try { await act(b.dataset.action); if (b.dataset.action.includes('backup')) ctx.reload(); } catch (x) {} finally { b.disabled = false; }
      return;
    }
    const del = e.target.closest('[data-delete-backup]');
    if (del) { if (!confirm('Delete backup ' + del.dataset.deleteBackup + '?')) return; await api.post('/api/backupdelete', { name: del.dataset.deleteBackup }); ctx.reload(); }
  });
  ctx.on($('#yt-form'), 'submit', async e => {
    e.preventDefault();
    const f = e.target; const body = { URLLink: f.URLLink.value, FileName: f.FileName.value, Media: f.Media.value, Scene: f.Scene.value };
    try { await act('/api/v1/youtube/import', body); f.URLLink.value = ''; f.FileName.value = ''; } catch (x) {}
  });
  ctx.on($('#backup-auto-btn'), 'click', async () => { await act('/api/v1/utilities/settings', { backup_auto: !d.backup_auto }); ctx.reload(); });
  ctx.on($('#media-roots-save'), 'click', () => act('/api/v1/utilities/settings', { media_search_roots: $('#media-roots').value }));
  const dmOnly = $('#dm-only'); if (dmOnly) ctx.on(dmOnly, 'change', async e => { await act('/api/v1/utilities/settings', { dm_only_sceneplay: e.target.checked }); store.set('sceneplayLocked', e.target.checked && !store.isDm()); });
  ctx.on($('#lights-off-end'), 'change', e => act('/api/v1/utilities/settings', { lights_off_on_scene_end: e.target.checked }));
  const aiForm = $('#ai-form'); if (aiForm) ctx.on(aiForm, 'submit', async e => {
    e.preventDefault(); const body = {};
    for (const [k, v] of new FormData(aiForm).entries()) body[k] = v;
    body.gemini_clear_key = !!aiForm.gemini_clear_key?.checked; body.runware_clear_key = !!aiForm.runware_clear_key?.checked;
    try { await act('/api/v1/utilities/ai-settings', body); ctx.reload(); } catch (x) {}
  });
  ctx.on($('#restart-computer'), 'click', async () => {
    if (!confirm('Are you sure you want to restart the computer? (Requires a DM login.)')) return;
    try { const r = await act('/api/v1/system/restart-computer', { sudo_password: $('#restart-sudo').value || null }); if (r.redirect) location.href = r.redirect; }
    catch (x) { if (x instanceof ApiError && x.code === 'dm_required') ctx.navigate('/login?next=/utilities'); if (x instanceof ApiError && x.code === 'setup_needed') ctx.navigate('/ttrpg/setup'); }
  });

  // import backup (multipart)
  ctx.on($('#import-form'), 'submit', async e => {
    e.preventDefault(); const f = e.target;
    const mode = f.mode.value;
    const ok = mode === 'replace'
      ? confirm('Replace ALL data on this server with the backup? A safety snapshot of the current state is taken first, and the app must be restarted afterwards.')
      : (f.full_merge.checked
        ? confirm('FULL merge — imports campaigns, scenes, media, homebrew libraries AND the whole TTRPG world: characters, sessions, battle maps, monsters, tokens, notes and scene lighting.\n\nNothing local is overwritten: same-named items combine, and a character that already exists here is kept as-is. Safe to re-run with the same file.\n\nContinue?')
        : confirm('Standard merge — imports campaigns, scenes, media and homebrew library entries ONLY.\n\nCharacters, sessions, battle maps and notes will NOT be imported. If you want those, cancel and tick "Full merge" first.\n\nContinue?'));
    if (!ok) return;
    const btn = f.querySelector('button'); btn.disabled = true; btn.textContent = 'Importing…';
    try { const r = await api.upload('/backup/import', new FormData(f)); toast.success(r.message, { ms: 20000 }); ctx.reload(); }
    catch (x) {} finally { btn.disabled = false; btn.textContent = 'Import'; }
  });

  // ── download queue + chimes ──
  const dlqPaint = q => {
    if (!q || !q.stats) return;
    for (const k of ['music', 'video']) {
      const s = q.stats[k];
      $('#dlq-' + k + '-remaining').textContent = s.remaining;
      $('#dlq-' + k + '-detail').textContent = s.queued + ' queued, ' + s.processing + ' downloading, ' + s.finished + ' done, ' + s.failed + ' failed' + (s.unavailable ? ', ' + s.unavailable + ' unavailable' : '');
      const rate = $('#dlq-' + k + '-rate'); rate.textContent = s.failure_rate + '%'; rate.style.color = s.failure_rate >= 25 ? '#c0392b' : (s.failure_rate > 0 ? '#b9770e' : '');
    }
    $('#dlq-failed-count').textContent = q.failed.length ? '(' + q.failed.length + ')' : '(none)';
    $('#dlq-retry-all').disabled = !q.failed.some(r => r.status === 4);
    $('#dlq-delete-all').disabled = !q.failed.some(r => r.status === 4);
    const tb = $('#dlq-table tbody');
    tb.innerHTML = q.failed.length ? '' : '<tr><td colspan="5" class="text-muted" style="padding:4px 6px;">No failed downloads.</td></tr>';
    q.failed.forEach(r => {
      const tr = document.createElement('tr'); tr.style.borderTop = '1px solid var(--sp-border)';
      tr.innerHTML = '<td style="padding:3px 6px;">' + (r.media_type === 'music' ? '&#9835; Song' : '&#9654; Video') + '</td>'
        + '<td style="padding:3px 6px;max-width:260px;word-break:break-word;">' + esc(r.name) + (r.url ? '<br><a href="' + esc(r.url) + '" target="_blank" rel="noopener" class="text-muted" style="font-size:.85em;">' + esc(r.url) + '</a>' : '') + '</td>'
        + '<td style="padding:3px 6px;white-space:nowrap;color:' + (r.status === 5 ? 'var(--sp-muted)' : '#c0392b') + ';">' + esc(r.status_label) + '</td>'
        + '<td style="padding:3px 6px;max-width:420px;word-break:break-word;font-family:monospace;font-size:.9em;">' + esc(r.error || '(no error captured)') + '</td>'
        + '<td style="padding:3px 6px;white-space:nowrap;"><button type="button" class="btn btn-sm btn-primary" data-dlq-retry="one" data-type="' + esc(r.media_type) + '" data-id="' + r.id + '">&#8635; Retry</button> <button type="button" class="btn btn-sm btn-outline-danger" data-dlq-delete="one" data-type="' + esc(r.media_type) + '" data-id="' + r.id + '" data-name="' + esc(r.name) + '" title="Remove this record entirely — its scene links, metadata and any partial file">&#10005; Delete</button></td>';
      tb.appendChild(tr);
    });
  };
  ctx.subscribe('downloads', dlqPaint, { fallback: { every: 5000, fetch: () => api.get('/api/downloads/status', { quiet: true }) } });
  api.get('/api/downloads/status', { quiet: true }).then(dlqPaint).catch(() => {});
  ctx.on(outlet, 'click', async e => {
    const r = e.target.closest('[data-dlq-retry]'), dl = e.target.closest('[data-dlq-delete]'); const msg = $('#dlq-msg');
    if (r) {
      const body = r.dataset.dlqRetry === 'one' ? { media_type: r.dataset.type, id: Number(r.dataset.id) } : { all: true, include_unavailable: r.dataset.dlqRetry === 'all-unavailable' };
      try { const d2 = await api.post('/api/downloads/retry', body, { quiet: true }); msg.textContent = d2.ok ? ('Re-queued ' + d2.requeued + ' — downloading now.') : (d2.error || 'Retry failed.'); } catch (x) { msg.textContent = 'Retry failed.'; }
    } else if (dl) {
      if (dl.dataset.dlqDelete === 'one') { if (!confirm('Remove "' + dl.dataset.name + '" from ScenePlay entirely? It is taken out of every scene it was added to.')) return; }
      else if (!confirm('Remove ' + (dl.dataset.dlqDelete === 'all-unavailable' ? 'every failed AND unavailable' : 'every failed') + ' download record from ScenePlay entirely? Each is taken out of every scene it was added to. This cannot be undone.')) return;
      const body = dl.dataset.dlqDelete === 'one' ? { media_type: dl.dataset.type, id: Number(dl.dataset.id) } : { all: true, include_unavailable: dl.dataset.dlqDelete === 'all-unavailable' };
      try { const d2 = await api.post('/api/downloads/delete', body, { quiet: true }); msg.textContent = d2.ok ? (d2.deleted !== undefined ? 'Removed ' + d2.deleted + '.' : 'Removed.') : (d2.error || 'Delete failed.'); } catch (x) { msg.textContent = x.message || 'Delete failed.'; }
    }
  });
  const chimePaint = c => {
    const tb = $('#chime-table tbody'); tb.innerHTML = '';
    c.events.forEach(ev => {
      const tr = document.createElement('tr');
      const opts = c.sounds.map(s => '<option value="' + esc(s) + '"' + (s === ev.file ? ' selected' : '') + '>' + esc(s) + (s === ev.default ? ' (default)' : '') + '</option>').join('');
      tr.innerHTML = '<td style="padding:2px 8px 2px 0;"><label class="form-check" style="margin:0;"><input class="form-check-input chime-on" type="checkbox" data-key="' + esc(ev.key) + '"' + (ev.enabled ? ' checked' : '') + '> <span class="form-check-label" title="' + esc(ev.help) + '">' + esc(ev.label) + '</span></label></td>'
        + '<td style="padding:2px 8px;"><select class="form-select form-select-sm chime-file" data-key="' + esc(ev.key) + '" style="width:auto;min-width:160px;">' + opts + '</select></td>'
        + '<td style="padding:2px 4px;"><button type="button" class="btn btn-sm btn-outline-secondary chime-preview" title="Preview">&#9654;</button></td>'
        + (ev.missing ? '<td class="small text-muted" style="padding:2px 8px;">chosen file missing — using default</td>' : '');
      tb.appendChild(tr);
    });
  };
  const chimeSave = async body => { const msg = $('#chime-msg'); try { const c = await api.post('/api/chimes', body, { quiet: true }); chimePaint(c); msg.textContent = 'Saved.'; } catch (x) { msg.textContent = x.message || 'Save failed.'; } };
  api.get('/api/chimes', { quiet: true }).then(chimePaint).catch(() => {});
  ctx.on($('#chime-table'), 'change', e => { const t = e.target; if (t.classList.contains('chime-on')) chimeSave({ key: t.dataset.key, enabled: t.checked }); else if (t.classList.contains('chime-file')) chimeSave({ key: t.dataset.key, file: t.value }); });
  ctx.on($('#chime-table'), 'click', e => { const b = e.target.closest('.chime-preview'); if (b) { const sel = b.closest('tr').querySelector('.chime-file'); new Audio('/chimes/sound/' + encodeURIComponent(sel.value)).play().catch(() => {}); } });
  ctx.on($('#chime-upload-btn'), 'click', async () => {
    const inp = $('#chime-upload'), msg = $('#chime-msg');
    if (!inp.files.length) { msg.textContent = 'Choose a sound file first.'; return; }
    const fd = new FormData(); fd.append('sound', inp.files[0]);
    try { const c = await api.upload('/api/chimes/upload', fd, { quiet: true }); chimePaint(c); msg.textContent = 'Added — pick it in a chime\'s dropdown.'; inp.value = ''; } catch (x) { msg.textContent = x.message || 'Upload failed.'; }
  });

  // ── software update ──
  (async () => {
    const status = $('#update-status'), list = $('#update-list'), btn = $('#update-btn'), logEl = $('#update-log');
    try {
      const u = await api.get('/api/update/check', { quiet: true });
      if (!u.git) { status.textContent = 'This copy was installed from a ZIP — to update, download the new ZIP from GitHub and re-run the installer.'; return; }
      if (u.error) { status.textContent = u.error; return; }
      if (!u.behind) { status.textContent = 'ScenePlay is up to date' + (u.current ? ' (' + u.current + ')' : '') + '.'; return; }
      status.textContent = 'Update available — ' + u.behind + ' change' + (u.behind === 1 ? '' : 's') + ':';
      u.commits.forEach(c => { const li = document.createElement('li'); li.textContent = c; list.appendChild(li); });
      list.style.display = ''; btn.style.display = ''; $('#update-sudo-row').style.display = '';
    } catch (e) { status.textContent = 'Could not check for updates (no internet?).'; }
    ctx.on(btn, 'click', async () => {
      if (!confirm('Update ScenePlay now?\n\nRecommended first: create a backup and download it to another computer (Backup & Restore section).\n\nA safety backup is also taken automatically, then the app restarts. Takes a few minutes.')) return;
      btn.disabled = true; status.textContent = 'Updating — this can take a few minutes. Leave this page open…';
      const sudoInput = $('#update-sudo'); const sudoPw = sudoInput.value; sudoInput.value = '';
      try {
        const r = await api.post('/api/update/run', { sudo_password: sudoPw }, { quiet: true });
        if (r.log) { logEl.textContent = r.log.join('\n'); logEl.style.display = ''; }
        if (r.error) { status.textContent = r.error; btn.disabled = false; return; }
        if (r.ok) { status.textContent = 'Update complete — restarting…'; ctx.after(1500, async () => { try { await api.post('/api/v1/system/restart'); } catch (x) {} location.href = '/restarting.html'; }); }
        else { status.textContent = 'Update failed — nothing was restarted. Details below.'; btn.disabled = false; }
      } catch (x) { if (x instanceof ApiError && x.code === 'dm_required') ctx.navigate('/login?next=/utilities'); else status.textContent = 'Update request failed: ' + x.message; btn.disabled = false; }
    });
  })();
}

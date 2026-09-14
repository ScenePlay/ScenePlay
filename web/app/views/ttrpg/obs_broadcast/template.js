// Broadcast (OBS) page markup — templates/ttrpg/obs_broadcast.html rendered
// from GET /api/v1/obs/page. The verbatim console.js drives it. The old
// form+redirect posts are <form data-api> (index.js submits them as
// multipart and re-mounts); the settings form auto-saves via fetch as before.
import { html, raw } from '../../../lib/dom.js';

const sel = on => (on ? raw(' selected') : '');
const chk = on => (on ? raw(' checked') : '');
const H6 = 'color:var(--ttrpg-accent);';
const SECTION = 'color:var(--ttrpg-accent);letter-spacing:.08em;text-transform:uppercase;font-size:.68rem;';
const BADGE_OWN = 'background:var(--ttrpg-accent);color:var(--sp-on-accent);font-size:.55rem;vertical-align:middle;';
const BADGE_SHARED = 'background:var(--ttrpg-primary);color:var(--ttrpg-text);border:1px solid var(--sp-border);font-size:.55rem;vertical-align:middle;';
const ALERT_RED = 'background:var(--ttrpg-primary);border:1px solid #c0392b;color:#e09090;';
const ALERT_AMBER = 'background:var(--ttrpg-primary);border:1px solid #c9a227;color:#8a6d1f;';

const DIRS = [['180', 'Top → bottom'], ['0', 'Bottom → top'], ['90', 'Left → right'], ['270', 'Right → left'],
  ['135', 'Top-left → bottom-right'], ['225', 'Top-right → bottom-left'], ['45', 'Bottom-left → top-right'],
  ['315', 'Bottom-right → top-left'], ['radial', 'Center glow (radial)']];
// Each preset is a colour STORY, not a tint swap: the base pair makes an
// analogous hue journey, and the plate pair sits on the accent's complement
// so the nameplates read against the scene instead of dissolving into it.
const THEMES = [
  ['Gilded night — gold over indigo night, brass plates', '#d2a95f', '#0b0c14', '#2a2118', '#3a2c14', '#14100a'],
  ['Steel — silver over gunmetal, verdigris plates', '#c2cdd6', '#0e1417', '#2e3b3f', '#232b25', '#0d1210'],
  ['Ember — fire over char, deep-teal plates', '#e0563f', '#140d0b', '#331c0c', '#0e2326', '#081214'],
  ['Verdant — leaf over forest, earthen plates', '#55b061', '#0a120c', '#26301b', '#2a1e10', '#100c07'],
  ['Arcane — violet over midnight, antique-gold plates', '#a678f0', '#110a20', '#2d1546', '#322608', '#131006'],
  ['Abyssal — sea-blue over deep water, brass-rust plates', '#52a8e8', '#06101c', '#0f3242', '#2a1a10', '#100a06'],
];
const FEED_TITLE = { live: 'Camera feed set, player online', ready: 'Camera feed set',
  stale: 'Camera feed set, but the player looks offline', nofeed: 'No camera feed yet' };
const FEED_COLOR = { live: '#28a745', ready: '#b8a24a', stale: '#c0392b', nofeed: '#555' };
const BEZEL_LABEL = { rounded: 'Rounded corners', square: 'Square', circle: 'Circle / oval', hex: 'Hexagon' };

const dirOptions = (name, id, cur) => html`<select name="${name}" ${id ? raw(`id="${id}"`) : ''} form="obs-cfg-form" class="form-select form-select-sm">
  ${DIRS.map(([v, label]) => html`<option value="${v}"${sel(cur === v)}>${label}</option>`)}</select>`;

const artWell = (art, w, h, r, video = true) => html`<div style="width:${w}px;height:${h}px;border-radius:${r}px;overflow:hidden;flex:0 0 auto;
     border:1px solid var(--sp-border);background:var(--ttrpg-primary);display:flex;align-items:center;justify-content:center;">
  ${art && art.url && art.is_video && video ? html`<video src="${art.url}" muted loop autoplay playsinline style="max-width:100%;max-height:100%;object-fit:contain;"></video>`
    : art && art.url && !art.is_video ? html`<img src="${art.url}" alt="" style="max-width:100%;max-height:100%;object-fit:contain;">`
    : html`<span class="small text-muted" style="font-size:.6rem;">none</span>`}</div>`;

const artBadge = art => (art.per_session
  ? html`<span class="badge ms-1" style="${BADGE_OWN}" title="This session's own art — other sessions keep theirs">this session</span>`
  : art.file ? html`<span class="badge ms-1" style="${BADGE_SHARED}" title="The shared default — used by any session without its own">shared</span>` : '');

const clearBtn = (art, formId) => (art.per_session
  ? html`<button name="clear" value="1" ${formId ? raw(`form="${formId}"`) : ''} class="btn btn-sm btn-outline-danger" title="Drop this session's art and fall back to the shared default">Clear</button>`
  : art.file ? html`<button name="clear" value="1" ${formId ? raw(`form="${formId}"`) : ''} class="btn btn-sm btn-outline-danger">Clear</button>` : '');

function partyRow(r, d) {
  const isDm = r.character_id === d.dm_id;
  return html`<div class="d-flex align-items-center gap-2 mb-2 obs-row flex-wrap" data-character-id="${r.character_id}" style="${r.on_stream ? '' : 'opacity:.55;'}">
    <label class="mb-0 d-flex align-items-center" style="cursor:pointer;" title="On the group feed. Untick to bench this player — they keep their seat in the session and their place in the running order, but lose their tile until you tick it back.">
      <input type="checkbox" class="obs-stream-chk" onchange="obsOnStream(this)"${chk(r.on_stream)}>
    </label>
    <span class="text-muted small obs-row-pos" style="width:1.3rem;text-align:right;">${r.pos || '·'}</span>
    <span class="obs-feed-dot" title="${FEED_TITLE[r.feed] || ''}" style="width:.6rem;height:.6rem;border-radius:50%;flex:0 0 auto;background:${FEED_COLOR[r.feed] || '#555'};"></span>
    <span style="min-width:9rem;">${r.name}${isDm ? html`<span class="badge ms-1" style="background:var(--ttrpg-accent);color:var(--sp-on-accent);font-size:.6rem;vertical-align:middle;">DM</span>` : ''}</span>
    <span class="small text-muted flex-grow-1">
      ${r.showing === 'card' ? html`showing stat card${r.feed === 'stale' ? html` <span class="text-warning">(camera dropped)</span>` : ''}` : 'showing camera'}
    </span>
    <label class="small text-muted mb-0 d-flex align-items-center gap-1" title="Pin this player to their stat card — use it when their camera drops and they aren't on the portal">
      <input type="checkbox" class="obs-card-chk" onchange="obsCardOverride(this)"${chk(r.show_card)}> card
    </label>
    <button type="button" class="btn btn-sm obs-mute-btn ${r.muted ? 'btn-danger' : 'btn-outline-secondary'}" data-muted="${r.muted ? '1' : '0'}" onclick="obsMuteChar(this)"
            title="${r.muted ? 'Muted on the stream — click to unmute' : 'Mute this voice on the stream'}">${raw(r.muted ? '&#128263;' : '&#128266;')}</button>
    <a class="btn btn-sm btn-outline-secondary" href="${isDm ? '/ttrpg/obs/feed/dm' : `/ttrpg/obs/feed/${r.character_id}`}" title="Camera link / QR code">&#128247;</a>
    <span class="text-muted" style="cursor:pointer;user-select:none;" onclick="obsReorder(${r.character_id}, -1)" title="Earlier in the rotation">&#9650;</span>
    <span class="text-muted" style="cursor:pointer;user-select:none;" onclick="obsReorder(${r.character_id}, 1)" title="Later in the rotation">&#9660;</span>
  </div>`;
}

function streamLook(cfg) {
  return html`<div class="mt-3" style="max-width:38rem;">
    <label class="form-label small mb-0">Stream look
      ${cfg.theme_own ? html`<span class="badge" style="background:var(--ttrpg-accent);color:var(--sp-on-accent);">this session's own</span>` : ''}
    </label>
    <div class="form-text mt-0 mb-1">
      Everything here re-skins a live stream within a few seconds &mdash; no source reloads. Saving with a session running styles <b>that session</b>; other sessions keep the shared look.
    </div>

    <div class="small fw-bold mt-2 mb-1" style="${SECTION}">Scene colours</div>
    <div class="row g-2 align-items-end">
      <div class="col-2"><label class="form-label small">Accent</label>
        <input type="color" name="obs_accent_color" id="obs-accent-input" form="obs-cfg-form" class="form-control form-control-sm" style="height:2rem;" value="${cfg.accent}"></div>
      <div class="col-2"><label class="form-label small">Base</label>
        <input type="color" name="obs_base_color" id="obs-base-input" form="obs-cfg-form" class="form-control form-control-sm" style="height:2rem;" value="${cfg.base}"></div>
      <div class="col-2"><label class="form-label small">Base 2</label>
        <input type="color" name="obs_base_color2" id="obs-base2-input" form="obs-cfg-form" class="form-control form-control-sm" style="height:2rem;" value="${cfg.base2}"></div>
      <div class="col-3"><label class="form-label small">Direction</label>${dirOptions('obs_base_dir', 'obs-basedir-input', cfg.base_dir)}</div>
      <div class="col-3"><label class="form-label small">Themes</label>
        <div class="d-flex gap-1 flex-wrap">
          ${THEMES.map(([name, a, b, b2, pl, pl2]) => html`<button type="button" class="btn btn-sm p-0" title="${name}"
                  style="width:1.8rem;height:1.6rem;border:1px solid #0006;background:linear-gradient(135deg, ${a} 25%, ${b} 25%, ${b2} 60%, ${pl} 60%, ${pl2});"
                  onclick="document.getElementById('obs-accent-input').value='${a}';document.getElementById('obs-base-input').value='${b}';document.getElementById('obs-base2-input').value='${b2}';document.getElementById('obs-plate-input').value='${pl}';document.getElementById('obs-plate2-input').value='${pl2}';obsAutoSave();"></button>`)}
        </div></div>
    </div>
    <div class="form-text">
      The <b>accent</b> paints frames, names, titles and headings. <b>Base &rarr; Base 2</b> blends across every surface in the chosen direction, with a faint dither so the stream encoder can't band it &mdash; keep them equal for a solid look. The theme buttons set the plate pair too; hover one for its colour story.
    </div>

    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">Camera tiles</div>
    <div class="row g-2 align-items-end">
      <div class="col-5"><label class="form-label small">Camera plate style</label>
        <select name="obs_tile_design" form="obs-cfg-form" class="form-select form-select-sm">
          ${[['strip', 'Full strip — face, name, HP'], ['tag', 'Name tag — compact pill'], ['third', 'Folder tab — full width']].map(([v, label]) => html`<option value="${v}"${sel(cfg.tile_design === v)}>${label}</option>`)}
        </select></div>
      <div class="col-7 small text-muted" style="padding-bottom:.4rem;">How much of the camera the plate covers. The <b>name tag</b> trades the player line for a clear picture; the <b>folder tab</b> runs edge to edge with a 45° step.</div>
    </div>
    <div class="row g-2 align-items-end mt-1">
      <div class="col-5"><label class="form-label small">Camera bezel</label>
        <select name="obs_bezel_shape" form="obs-cfg-form" class="form-select form-select-sm">
          ${(cfg.bezel_shapes || []).map(s => html`<option value="${s}"${sel(cfg.bezel === s)}>${BEZEL_LABEL[s] || s}</option>`)}
        </select></div>
      <div class="col-7 small text-muted" style="padding-bottom:.4rem;">The frame around every camera. The plate rides on top, so no shape ever cuts a name off.</div>
    </div>
    <div class="row g-2 align-items-end mt-1">
      <div class="col-2"><label class="form-label small">Plate</label>
        <input type="color" name="obs_plate_color" id="obs-plate-input" form="obs-cfg-form" class="form-control form-control-sm" style="height:2rem;" value="${cfg.plate}"></div>
      <div class="col-2"><label class="form-label small">Plate 2</label>
        <input type="color" name="obs_plate_color2" id="obs-plate2-input" form="obs-cfg-form" class="form-control form-control-sm" style="height:2rem;" value="${cfg.plate2}"></div>
      <div class="col-4"><label class="form-label small">Plate direction</label>${dirOptions('obs_plate_dir', '', cfg.plate_dir)}</div>
      <div class="col-4 small text-muted" style="padding-bottom:.4rem;">The name plate's own pair; unset, it follows the base colours.</div>
    </div>

    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">The DM on stream</div>
    <div class="row g-2 align-items-end">
      <div class="col-3"><label class="form-label small">Badge</label>
        <select name="obs_dm_icon" form="obs-cfg-form" class="form-select form-select-sm" style="font-size:1rem;">
          ${(cfg.dm_icons || []).map(i => html`<option value="${i}"${sel(cfg.dm_icon === i)}>${i}</option>`)}
        </select></div>
      <div class="col-4"><label class="form-label small">Title</label>
        <input type="text" name="obs_dm_title" form="obs-cfg-form" class="form-control form-control-sm" maxlength="40" value="${cfg.dm_title}" placeholder="Dungeon Master"></div>
      <div class="col-5 small text-muted" style="padding-bottom:.4rem;">The symbol on the DM's portrait spot and the line under their name &mdash; Game Master, Storyteller, The AI&hellip;</div>
    </div>

    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">Stat cards</div>
    <div class="row g-2 align-items-end">
      <div class="col-5"><label class="form-label small">Card design</label>
        <select name="obs_card_design" form="obs-cfg-form" class="form-select form-select-sm">
          ${[['classic', 'Classic — centred'], ['banner', 'Banner — portrait left'], ['trading', 'Trading — token frame']].map(([v, label]) => html`<option value="${v}"${sel(cfg.card_design === v)}>${label}</option>`)}
        </select></div>
      <div class="col-7 small text-muted" style="padding-bottom:.4rem;">The layout a player's card uses when their camera is off.</div>
    </div>
    ${cfg.theme_own ? html`<div class="mt-2"><button type="submit" form="obs-theme-shared-form" class="btn btn-sm btn-outline-secondary">Back to the shared look</button></div>` : ''}
  </div>`;
}

function showCard(kind, label, slot, cfg) {
  const c = cfg[kind] || {};
  const art = (cfg.images || []).find(i => i.slot === slot) || {};
  return html`<div class="border rounded p-2 mb-2" style="border-color:var(--sp-border) !important;">
    <div class="row g-2 align-items-end">
      <div class="col-5"><label class="form-label small">${label} title</label>
        <input type="text" name="obs_${kind}_title" form="obs-cfg-form" class="form-control form-control-sm" maxlength="120" value="${c.title || ''}" placeholder="(no title)"></div>
      <div class="col-4"><label class="form-label small">Placed</label>
        <select name="obs_${kind}_title_pos" form="obs-cfg-form" class="form-select form-select-sm">
          ${(cfg.title_positions || []).map(p => html`<option value="${p}"${sel(c.pos === p)}>${p.replace(/-/g, ' ')}</option>`)}
        </select></div>
      <div class="col-3 small text-muted" style="padding-bottom:.4rem;">${kind === 'pre' ? "artwork doubles as the battle map's idle screen" : ''}</div>
    </div>
    <div class="d-flex align-items-center gap-2 mt-2 flex-wrap">
      ${artWell(art, 66, 38, 5)}
      <div class="small text-muted" style="font-size:.7rem;line-height:1.25;min-width:7rem;flex:1 1 auto;">
        ${art.file ? html`<code>${art.file}</code>` : 'not set'} ${artBadge(art)}
      </div>
      <div class="d-flex align-items-center gap-1 flex-shrink-0">
        <input type="file" name="image" accept="image/*,video/mp4,video/webm" form="obs-art-${slot}" class="form-control form-control-sm" style="max-width:12rem;" onchange="if (this.files.length) _obsSubmitForm(this.form);">
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="pasteImageNear(this)" title="Paste an image from the clipboard">&#128203;</button>
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="obsReuseArt(document.getElementById('obs-art-${slot}'), ['image','video'])" title="Reuse a picture or video already on this server — nothing is copied">&#128444;</button>
        ${clearBtn(art, `obs-art-${slot}`)}
      </div>
    </div>
  </div>`;
}

function showArt(cfg) {
  const bg = (cfg.images || []).find(i => i.slot === 'party_bg') || {};
  return html`<div class="ttrpg-card p-3 mb-3">
    <h6 style="${H6}" class="mb-2">&#128247; Show art</h6>
    <p class="small text-muted">
      A picture or <b>looping video</b> (MP4/WEBM) that sits behind every ScenePlay scene &mdash; the party grid, the battle map and the show cards all render over it. With a session running the upload belongs to <b>that session</b>, falling back to the shared default. Choose a file or paste from the clipboard; it saves immediately. Each show card's own artwork is set with the card, just below.
    </p>
    <div style="display:grid;grid-template-columns:88px minmax(9rem,1fr) auto auto;gap:.5rem .75rem;align-items:center;">
      ${artWell(bg, 88, 50, 6)}
      <div class="small" style="line-height:1.25;">
        ${bg.label || ''} ${artBadge(bg)}
        <div class="text-muted" style="font-size:.7rem;">${bg.file ? html`<code>${bg.file}</code>` : 'not set'}</div>
      </div>
      <form method="post" enctype="multipart/form-data" action="/ttrpg/obs/image/party_bg" data-api="/ttrpg/obs/image/party_bg" data-multipart="1" class="d-flex align-items-center gap-1" style="margin:0;">
        <input type="file" name="image" accept="image/*,video/mp4,video/webm" class="form-control form-control-sm" style="max-width:13rem;" onchange="if (this.files.length) _obsSubmitForm(this.form);">
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="pasteImageNear(this)" title="Paste an image from the clipboard">&#128203;</button>
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="obsReuseArt(this.form, ['image','video'])" title="Reuse a picture or video already on this server — nothing is copied">&#128444;</button>
      </form>
      <form method="post" action="/ttrpg/obs/image/party_bg" data-api="/ttrpg/obs/image/party_bg" data-multipart="1" style="margin:0;">
        ${bg.per_session || bg.file ? clearBtn(bg, '') : html`<span class="small text-muted" style="font-size:.7rem;">&nbsp;</span>`}
      </form>
    </div>
    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">Show cards &mdash; pre / intermission / post</div>
    <div class="ms-3" style="max-width:44rem;">
      <div class="form-text mb-2">
        Three scenes to open, break and close the stream. Each shows its artwork at 75% of the canvas over the shared background, with a title you can place. Everything for one card lives here: its title, where the title sits, and the artwork itself.
      </div>
      ${showCard('pre', 'Pre-show', 'title', cfg)}
      ${showCard('intermission', 'Intermission', 'intermission', cfg)}
      ${showCard('post', 'Post-show', 'post', cfg)}
      <div class="form-text">
        Titles and placement save automatically like every setting; artwork uploads the moment you choose or paste a file. Pictures or looping videos (MP4/WEBM); with a session running, uploads belong to that session.
      </div>
    </div>
  </div>`;
}

function mapCard(cfg, d) {
  return html`<div class="ttrpg-card p-3 mb-3">
    <div class="d-flex align-items-center justify-content-between mb-2"><h6 style="${H6}" class="mb-0">Battle Map on Stream</h6></div>
    <p class="small text-muted">
      The map is a <b>browser source</b> &mdash; just the map, not your screen or a browser window. It follows the live map, shows it through the active player's eyes (fog and all), and falls back to your title card when no map is running. <b>Build / refresh party scene</b> creates the <code>${cfg.map_scene}</code> scene for you to cut to.
    </p>
    <div class="row g-2 align-items-end mb-3">
      <div class="col-sm-7">
        <label class="form-label small">Render the map as</label>
        <div class="d-flex gap-2 flex-wrap">
          <button type="button" id="obs-mode-auto" class="btn btn-sm flex-grow-1" onclick="obsSetMapMode('auto')">&#127916; Auto</button>
          <button type="button" id="obs-mode-2d" class="btn btn-sm flex-grow-1" onclick="obsSetMapMode('2d')">&#128506; 2D top-down</button>
          <button type="button" id="obs-mode-3d" class="btn btn-sm flex-grow-1" onclick="obsSetMapMode('3d')">&#127760; 3D through the player</button>
        </div>
        <div class="form-text">
          Takes effect on the stream within a couple of seconds &mdash; no saving, no reload. <b>Auto</b> holds the 2D map and cuts to 3D only when the featured player moves, runs one look-around, then cuts back. 3D needs a floorplan and a player on the map; without either it shows 2D.
        </div>
      </div>
      <div class="col-sm-5">
        <label class="form-label small">Map source in OBS</label>
        <button type="button" class="btn btn-sm btn-outline-secondary w-100" onclick="obsReloadMap(this)">&#8635; Reload map source</button>
        <button type="button" class="btn btn-sm btn-outline-secondary w-100 mt-1" onclick="obsReloadAll(this)">&#8635; Reload ALL ScenePlay sources</button>
        <div class="form-text">OBS keeps a browser source's page loaded until you reload it, so after a ScenePlay update the stream can still be running the old map page. Use this if the map ignores a setting you just changed.</div>
      </div>
    </div>
    <div class="row g-2 align-items-end mb-3">
      <div class="col-sm-5">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="obs-map-zoom" name="obs_map_zoom" value="1" form="obs-cfg-form"${chk(cfg.map_zoom === '1')}>
          <label class="form-check-label small" for="obs-map-zoom">Action camera <span class="text-muted">&mdash; push in on the party, ease back out when nobody has moved</span></label>
        </div>
      </div>
      <div class="col-sm-3"><label class="form-label small">Max zoom</label>
        <input type="number" name="obs_map_zoom_max" form="obs-cfg-form" class="form-control form-control-sm" min="1" max="6" step="0.1" value="${cfg.map_zoom_max}"></div>
      <div class="col-sm-4"><label class="form-label small">Pull back after (s)</label>
        <input type="number" name="obs_map_zoom_hold_s" form="obs-cfg-form" class="form-control form-control-sm" min="1" max="120" step="1" value="${cfg.map_zoom_hold}">
        <div class="form-text">Saves automatically.</div></div>
      <div class="col-sm-4"><label class="form-label small">Stat card refresh (s)</label>
        <input type="number" name="obs_card_poll_s" form="obs-cfg-form" class="form-control form-control-sm" min="2" max="120" step="1" value="${cfg.card_poll}">
        <div class="form-text">Paid once per player card, so the request rate is this divided by the size of the party. Raise it if the log is noisy.</div></div>
    </div>
    <div class="row g-2 align-items-end mb-2">
      <div class="col-sm-12">
        <a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" data-native href="${d.map_preview_url}">Preview the map source</a>
        <span class="small text-muted ms-2">Opens exactly what OBS renders.</span>
      </div>
    </div>
  </div>`;
}

function sceneLinks(d) {
  const snap = d.snap;
  if (!d.scene_rows || !d.scene_rows.length) return '';
  return html`<div class="ttrpg-card p-3 mb-3">
    <h6 style="${H6}" class="mb-2">Scene Links</h6>
    <p class="small text-muted">
      Activating one of your ScenePlay scenes can cut OBS at the same time &mdash; e.g. a battle scene switches to the map view (needs <i>Switch OBS when a ScenePlay scene is activated</i> below) &mdash; and can set the stream's voices: give PreShow <b>Mute everyone</b> and the table talks freely off-air while the card is up, then let your opening scene <b>Unmute everyone</b>.
    </p>
    ${!snap.scenes.length ? html`<div class="small mb-2" style="color:#c9a227;">&#9888; OBS isn't connected, so its scene list is empty. You can still type a scene name below &mdash; it's matched when the scene activates.</div>` : ''}
    <datalist id="obs-scene-names">${snap.scenes.map(o => html`<option value="${o}"></option>`)}</datalist>
    ${d.scene_rows.map(s => html`<div class="d-flex align-items-center gap-2 mb-2 obs-scene-row flex-wrap" data-scene-id="${s.scene_id}">
      <span style="min-width:11rem;">${s.name}</span>
      <input type="text" class="form-control form-control-sm obs-scene-link" style="max-width:18rem;" list="obs-scene-names" value="${s.obs_scene}" placeholder="— no OBS switch —" onchange="obsSaveSceneLink(this)">
      <select class="form-select form-select-sm obs-scene-audio" style="max-width:13rem;" onchange="obsSceneAudio(this)" title="What activating this scene does to the STREAM's voices — the room keeps talking either way">
        ${[['', '— audio unchanged —'], ['mute_all', 'Mute everyone'], ['mute_players', 'Mute players'], ['unmute_all', 'Unmute everyone']].map(([v, lbl]) => html`<option value="${v}"${sel(s.audio === v)}>${lbl}</option>`)}
      </select>
      <span class="small obs-scene-note" style="min-width:9rem;">${s.obs_scene && snap.scenes.length && !snap.scenes.includes(s.obs_scene) ? html`<span style="color:#c9a227;">&#9888; not in OBS</span>` : ''}</span>
    </div>`)}
  </div>`;
}

function rigCard(cfg) {
  const rig = cfg.rig || {};
  return html`<div class="ttrpg-card p-3 mb-3">
    <div class="d-flex align-items-center justify-content-between mb-2">
      <h6 style="${H6}" class="mb-0">&#128421; Where OBS is running</h6>
      <span class="badge" style="${rig.local ? 'background:var(--ttrpg-accent);color:var(--sp-on-accent)' : 'background:var(--ttrpg-primary);color:#8a6d1f;border:1px solid #c9a227'};">${rig.where}</span>
    </div>
    <div class="small mb-2"><span class="text-muted">Connecting to</span> <code>${rig.host}</code> ${rig.platform ? html`<span class="text-muted">&mdash; ${rig.platform}</span>` : ''}</div>
    <div class="row g-2 small">
      <div class="col-sm-6">
        <div class="fw-bold" style="${H6}">${rig.local ? 'Same machine' : 'Different machine'}</div>
        <ul class="mb-0 ps-3 text-muted">
          ${rig.local ? html`<li>Pages can load from this machine directly.</li><li>Music is <b>monitored</b> off the audio device.</li><li>Nothing extra to keep open.</li>`
    : html`<li>Pages must load over the <b>LAN address</b>, never localhost.</li><li>Music must be <b>streamed</b> &mdash; OBS cannot reach this machine's audio devices.</li><li>This machine has to stay reachable for the whole session.</li>`}
        </ul>
      </div>
      <div class="col-sm-6">
        <div class="fw-bold" style="${H6}">Music path: ${rig.transport}</div>
        <div class="text-muted">${rig.music_why}</div>
      </div>
    </div>
    ${(rig.problems || []).length ? html`<div class="alert py-2 px-3 mb-0 mt-2" style="${ALERT_RED}"><ul class="mb-0 ps-3">${rig.problems.map(p => html`<li>${p}</li>`)}</ul></div>` : ''}
    ${(rig.steps || []).length ? html`<div class="form-text mt-2 mb-0"><b>For this setup:</b><ul class="mb-0 ps-3">${rig.steps.map(s => html`<li>${s}</li>`)}</ul></div>` : ''}
  </div>`;
}

function pageAddressCard(cfg) {
  return html`<div class="ttrpg-card p-3 mb-3">
    <div class="d-flex align-items-center justify-content-between mb-2"><h6 style="${H6}" class="mb-0">&#127760; Page address for OBS</h6></div>
    ${cfg.card_base_loopback ? html`<div class="alert py-2 px-3 mb-2" style="${ALERT_AMBER}">
      &#9888; This is a <b>loopback</b> address, so it only works when OBS runs on <i>this same machine</i>. On another computer &mdash; a Mac running OBS, for example &mdash; <code>localhost</code> means <i>that</i> computer, so every ScenePlay source loads nothing even though the connection is fine.
      ${cfg.card_base_lan !== cfg.card_base ? html`Use <code>${cfg.card_base_lan}</code> instead.` : ''}
    </div>` : ''}
    ${cfg.card_base_stale ? html`<div class="alert py-2 px-3 mb-2" style="${ALERT_AMBER}">
      &#9888; This machine now answers on <code>${cfg.card_base_lan}</code>, not <code>${cfg.card_base}</code> &mdash; its address has changed since this was saved. Every ScenePlay source will render <b>blank</b> until it is updated, while OBS still connects perfectly over the websocket. Use the button below, then rebuild the party scene.
    </div>` : ''}
    <div class="row g-2 align-items-end">
      <div class="col-sm-7">
        <label class="form-label small" for="obs-card-base">Base URL OBS should load pages from</label>
        <div class="input-group input-group-sm">
          <input type="text" name="obs_card_base" form="obs-cfg-form" id="obs-card-base" class="form-control form-control-sm" value="${cfg.card_base}" placeholder="${cfg.card_base_lan}">
          <button class="btn btn-sm btn-outline-secondary" type="button" onclick="obsUseThisMachine(this)" title="Fill in the address this machine is reachable on">Use this machine</button>
        </div>
      </div>
      <div class="col-sm-5">
        <div class="form-text mb-1">This machine on the LAN: <code>${cfg.card_base_lan}</code></div>
        <div class="form-text">Filled in automatically the first time you opened this page. Saves automatically &mdash; rebuild the party scene afterwards so existing sources are repointed.</div>
      </div>
    </div>
  </div>`;
}

function musicBlocks(cfg) {
  return html`<div class="small fw-bold mt-3 mb-1" style="${SECTION}">Music on the stream</div>
    <div class="mb-2">
      <label class="form-label small mb-1" for="obs-music-transport"><b>Music into OBS</b> &mdash; how it gets there</label>
      <select name="obs_music_transport" id="obs-music-transport" form="obs-cfg-form" class="form-select form-select-sm" style="max-width:26rem;" onchange="obsPaintMusicPath()">
        ${[['auto', 'Automatic — pick for me'], ['device', 'Monitor the local audio device'], ['feed', 'Send it as a vdo.ninja feed'], ['off', 'Do not send music to OBS']].map(([m, lbl]) => html`<option value="${m}"${sel(cfg.music_transport === m)}>${lbl}</option>`)}
      </select>
      <div class="form-text small">In use: <b id="obs-music-now">${cfg.music_resolved}</b> &mdash; ${cfg.obs_local ? 'OBS is on this machine' : 'OBS is on another machine'}</div>
      <div class="form-text small" id="obs-music-forced" style="color:#c9a227;${cfg.music_forced ? '' : 'display:none;'}">
        &#9888; This is a <b>manual</b> choice, so it stays put even when moving OBS would call for the other one. <b>Automatic</b> would use <b>${cfg.obs_local ? 'device' : 'feed'}</b> right now.
      </div>
    </div>

    <div class="ttrpg-card p-2 mb-2" id="obs-music-device-block">
      <div class="small fw-bold mb-1" style="${H6}">Monitoring the local device</div>
      <div class="small text-muted">
        Takes the music player's own output &mdash; <code>${cfg.music_device}</code> &mdash; straight into the party scene, which every other scene inherits. Only the music is on that device, so it can never pick your players back up and loop. Nothing to open and nothing to keep running. <b>Only works when OBS is on this machine.</b>
      </div>
    </div>

    <div class="ttrpg-card p-2 mb-2" id="obs-music-feed-block">
      <div class="small fw-bold mb-1 d-flex justify-content-between align-items-baseline" style="${H6}">
        <span>Sending it as a vdo.ninja feed</span>
        ${cfg.music_cable ? html`<a href="#" class="small fw-normal" data-native data-bs-toggle="modal" data-bs-target="#obs-music-win-help">Windows setup guide</a>` : ''}
      </div>
      ${cfg.music_cable ? html`<div class="mb-2">
        <label class="form-label small mb-1" for="obs-music-out">Music output device <span class="text-muted">(this machine)</span></label>
        <select name="music_output_device" id="obs-music-out" form="obs-cfg-form" class="form-select form-select-sm">
          ${(cfg.music_outs || []).map(([dev, lbl]) => html`<option value="${dev}"${sel(cfg.music_out === dev)}>${lbl}</option>`)}
        </select>
        <div class="form-text small">Where the music player sends its sound. Windows cannot capture a speaker output, so pick your cable's <b>input</b> (e.g. <code>CABLE Input (VB-Audio Virtual Cable)</code>) &mdash; then tick <b>Listen to this device</b> on <code>CABLE Output</code> in Windows Sound &rarr; Recording, or you will stop hearing the music yourself. Takes effect on the next track.</div>
      </div>` : ''}
      <div class="row g-2 align-items-end">
        <div class="col-sm-7">
          <label class="form-label small mb-1" for="obs-music-label">Audio device vdo.ninja should send</label>
          <select name="obs_music_device_label" id="obs-music-label" form="obs-cfg-form" class="form-select form-select-sm">
            ${(cfg.music_label_opts || []).map(([val, lbl]) => html`<option value="${val}"${sel(cfg.music_label === val)}>${lbl}</option>`)}
          </select>
          <div class="form-text small">
            Matched on the device <em>label</em>.
            ${cfg.music_cable ? html`On this machine that is the cable's <b>output</b> &mdash; <code>CABLE Output</code> &mdash; the recording end of what you picked above. <code>ScenePlay-Music</code> is Linux-only and will match nothing here.`
    : html`On this machine <code>ScenePlay-Music</code> &mdash; the source ScenePlay builds itself &mdash; is already the right answer; leave it unless you route the music through a real device.`}
          </div>
        </div>
        <div class="col-sm-5">
          <a class="btn btn-sm btn-ttrpg w-100" target="_blank" rel="noopener" data-native id="obs-music-start" href="${cfg.music_push}">&#9835; Start the music feed</a>
          <div class="form-text small">Open this <b>on the machine playing the music</b> and leave the tab running &mdash; music only, no camera or microphone.</div>
        </div>
      </div>
    </div>
    ${cfg.music_cable ? winHelpModal() : ''}`;
}

function winHelpModal() {
  return html`<div class="modal fade" id="obs-music-win-help" tabindex="-1" aria-labelledby="obs-music-win-help-title" aria-hidden="true">
    <div class="modal-dialog modal-lg modal-dialog-scrollable">
      <div class="modal-content" style="background:var(--sp-surface);color:var(--sp-text);border:1px solid var(--sp-border);">
        <div class="modal-header" style="border-color:var(--sp-border);">
          <h5 class="modal-title fs-6" id="obs-music-win-help-title" style="${H6}">Music &rarr; OBS from Windows</h5>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body small">
          <p class="mb-2">Windows has no capture sink for the music, so it travels through a <b>virtual audio cable</b>: the player sends sound into one end, the feed tab captures the other. Every step is one-time setup.</p>
          <pre class="p-2 mb-3" style="background:var(--sp-surface-2);color:var(--sp-text);border:1px solid var(--sp-border);border-radius:var(--sp-radius);overflow-x:auto;">music player &rarr; CABLE Input &#9655; CABLE Output &rarr; feed tab &rarr; OBS
                                    &#9584;&rarr; "Listen" &rarr; your speakers</pre>
          <div class="fw-bold mb-1" style="${H6}">1. Install VB-CABLE <span class="text-muted fw-normal">(once)</span></div>
          <p class="mb-2">Download from <a href="https://vb-audio.com/Cable/" target="_blank" rel="noopener" data-native>vb-audio.com/Cable</a>, run the installer <b>as administrator</b>, reboot. Do <b>not</b> make the cable the Windows default output &mdash; only the music belongs in it.</p>
          <div class="fw-bold mb-1" style="${H6}">2. Point both ends at it <span class="text-muted fw-normal">(this page, below)</span></div>
          <p class="mb-2"><b>Music output device</b> &rarr; <code>CABLE Input</code>. <b>Device vdo.ninja should send</b> &rarr; <code>CABLE Output</code>. The player picks up the device on the <b>next track</b>, so skip one after changing it. (<code>ScenePlay-Music</code> is the Linux default and matches nothing on Windows.)</p>
          <div class="fw-bold mb-1" style="${H6}">3. Keep hearing it yourself</div>
          <p class="mb-2">The cable takes the music off your speakers. Mirror it back: <kbd>Win</kbd>+<kbd>R</kbd> &rarr; <code>mmsys.cpl</code> &rarr; <b>Recording</b> &rarr; double-click <b>CABLE Output</b> &rarr; <b>Listen</b> tab &rarr; tick <b>Listen to this device</b> &rarr; play back through your real speakers. It cannot echo into the stream &mdash; the feed reads the cable, not the speakers.</p>
          <div class="fw-bold mb-1" style="${H6}">4. Start the feed</div>
          <p class="mb-2">Click <b>&#9835; Start the music feed</b> and leave the tab open (audio only &mdash; no camera). Allow the microphone prompt: the "microphone" is the cable. Reopen the link after changing settings &mdash; the device name is baked into it. In OBS, the <b>ScenePlay Music Feed</b> meter should move.</p>
          <div class="fw-bold mb-1" style="${H6}">If it is silent, walk the chain</div>
          <div class="table-responsive">
            <table class="table table-sm ttrpg-table mb-1">
              <thead><tr><th>Check</th><th>If dead</th></tr></thead>
              <tbody>
                <tr><td>Green bar on <b>CABLE Output</b> in <code>mmsys.cpl</code> &rarr; Recording</td><td>Step 2's output device &mdash; then skip to the next track.</td></tr>
                <tr><td>Audio meter in the feed tab</td><td>Step 2's send label &mdash; then close and reopen the tab.</td></tr>
                <tr><td>Mixer meter in OBS</td><td>Rebuild scenes; check the OBS machine reaches vdo.ninja.</td></tr>
                <tr><td>Your speakers</td><td>Step 3's "Listen to this device".</td></tr>
              </tbody>
            </table>
          </div>
          <div class="text-muted">Full guide with details: <code>docs/OBS_MUSIC_WINDOWS.md</code> in the ScenePlay folder.</div>
        </div>
      </div>
    </div>
  </div>`;
}

function settingsForm(cfg, d) {
  const snap = d.snap;
  return html`<form method="post" action="/ttrpg/obs/save-config" id="obs-cfg-form" onsubmit="obsAutoSave(); return false;">
    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">Scenes &amp; switching</div>
    <div class="row g-2 mb-3">
      <div class="col-sm-8">
        <label class="form-label small">Group shot scene <span class="text-muted">— everyone on screen</span></label>
        <select name="obs_group_scene" class="form-select form-select-sm">
          <option value="">— none —</option>
          ${snap.scenes.map(s => html`<option value="${s}"${sel(s === cfg.group_scene)}>${s}</option>`)}
          ${cfg.group_scene && !snap.scenes.includes(cfg.group_scene) ? html`<option value="${cfg.group_scene}" selected>${cfg.group_scene} (missing in OBS)</option>` : ''}
        </select>
      </div>
      <div class="col-sm-4">
        <label class="form-label small">Auto-return after (s)</label>
        <input type="number" name="obs_auto_return_s" class="form-control form-control-sm" min="0" max="3600" step="5" value="${cfg.auto_return_s}">
        <div class="form-text">0 = stay put.</div>
      </div>
    </div>
    <div class="form-check mb-3">
      <input class="form-check-input" type="checkbox" id="obs-scene-link" name="obs_scene_link" value="1"${chk(cfg.scene_link === '1')}>
      <label class="form-check-label small" for="obs-scene-link">Switch OBS when a ScenePlay scene is activated <span class="text-muted">(uses the Scene Links above)</span></label>
    </div>
    <div class="row g-2 mb-3">
      <div class="col-sm-8">
        <label class="form-label small">Transition when switching</label>
        <select name="obs_transition" class="form-select form-select-sm">
          <option value="">— leave whatever OBS is set to —</option>
          ${(snap.transitions || []).map(t => html`<option value="${t.name}"${sel(t.name === cfg.transition)}>${t.name}</option>`)}
        </select>
      </div>
      <div class="col-sm-4">
        <label class="form-label small">Duration (ms)</label>
        <input type="number" name="obs_transition_ms" class="form-control form-control-sm" min="0" max="20000" step="50" value="${cfg.transition_ms}">
      </div>
    </div>
    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">The table's camera room</div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="obs-feed-noaudio" name="obs_feed_noaudio" value="1"${chk(cfg.feed_noaudio === '1')}>
      <label class="form-check-label small" for="obs-feed-noaudio">
        Camera tiles carry <b>video only</b> <span class="text-muted">(drops the audio track from the tiles, for when the players' audio already reaches OBS another way and you do not want it twice. This is <b>not</b> a fix for black tiles &mdash; OBS starts a feed with audio just fine.)</span>
      </label>
    </div>
    <div class="mb-3">
      <label class="form-label small mb-1" for="obs-vdo-room">Table room <span class="text-muted">— how players hear each other</span></label>
      <div class="input-group input-group-sm">
        <input class="form-control form-control-sm" id="obs-vdo-room" name="obs_vdo_room" form="obs-cfg-form" value="${cfg.vdo_room}" placeholder="no room — players cannot hear each other">
        <button class="btn btn-sm btn-outline-secondary" type="button" onclick="obsNewRoom(this)" title="Create a new room and put the whole table in it">${cfg.vdo_room ? 'New room' : 'Create room'}</button>
      </div>
      <div class="form-text small" id="obs-room-note">
        ${cfg.vdo_room ? html`Every camera link &mdash; players' and yours &mdash; now joins this room, so the table hears each other directly. OBS still watches each player <em>individually</em>, so every camera keeps its own fader in the Audio Mixer. Anyone already holding an old link must reopen their camera page to pick the room up.`
    : html`Without a room each player is a lone stream that only OBS ever listens to &mdash; they cannot hear each other or you. Create one, or paste the name of a room you already use.`}
      </div>
      <div class="row g-2 align-items-end mt-1">
        <div class="col-sm-7">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="obs-room-video" name="obs_room_video" value="1" form="obs-cfg-form"${chk(cfg.room_audio_only !== '1')}>
            <label class="form-check-label small" for="obs-room-video">
              Players <b>see</b> each other's video in the room <span class="text-muted">(off = voices only between players, which is the safe default: with a full table every camera would otherwise upload to nine peers <em>and</em> OBS at once, which chokes phones and home upload. Faces still reach everyone through the stream either way.)</span>
            </label>
          </div>
        </div>
        <div class="col-sm-5">
          <label class="form-label small mb-1" for="obs-room-bitrate">Camera bitrate ceiling (kbps)</label>
          <input type="number" name="obs_room_videobitrate" id="obs-room-bitrate" form="obs-cfg-form" class="form-control form-control-sm" min="200" max="8000" step="100" value="${cfg.room_videobitrate}">
          <div class="form-text small">Hard cap per camera. Applies after players reopen their links.</div>
        </div>
      </div>
      ${cfg.room_join_url ? html`<div class="mt-2">
        <a class="btn btn-sm btn-ttrpg" target="_blank" rel="noopener" data-native href="${cfg.room_join_url}">&#127908; Join the room</a>
        <span class="small text-muted ms-2">Your own camera and microphone, in the room with everyone. Wear headphones &mdash; every live mic in the room is now playing out of your speakers and back into itself otherwise.</span>
      </div>` : ''}
    </div>
    <div class="mb-3">
      <label class="form-label small">Shared camera password <span class="text-muted">— protects every player's feed</span></label>
      <input type="password" name="obs_vdo_password" class="form-control form-control-sm" placeholder="${cfg.has_vdo_password ? 'leave blank to keep existing' : 'recommended — one secret for the whole table'}" value="" autocomplete="new-password">
      <div class="form-text">
        Baked into every player's link, so a leaked link alone isn't enough to watch a feed. Changing it changes everyone's links.
        ${cfg.has_vdo_password ? html`<label class="ms-2"><input type="checkbox" name="obs_vdo_password_clear" value="1"> clear it</label>` : ''}
      </div>
    </div>
    ${musicBlocks(cfg)}

    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">You — the DM's tile &amp; audio</div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="obs-feed-monitor" name="obs_feed_monitor" value="1"${chk(cfg.feed_monitor === '1')}>
      <label class="form-check-label small" for="obs-feed-monitor">
        <b>Play the players out loud</b> here <span class="text-muted">(the feeds always reach the stream. Tick this only if OBS is how <em>you</em> hear your players &mdash; if you are already on a voice call, you will hear everyone twice. Needs a monitoring device set in OBS under Settings &rarr; Audio.)</span>
      </label>
    </div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="obs-dm-audio" name="obs_dm_audio" value="1"${chk(cfg.dm_audio === '1')}>
      <label class="form-check-label small" for="obs-dm-audio">
        Your own tile carries <b>your</b> audio <span class="text-muted">(off by default: your camera tile is your own microphone coming back to you, so it doubles your voice on the broadcast and can howl if you are monitoring. Leave it off and let your real mic input carry you.)</span>
      </label>
    </div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="obs-dm-enabled" name="obs_dm_enabled" value="1"${chk(d.dm_enabled)}>
      <label class="form-check-label small" for="obs-dm-enabled">Give the DM a tile in the party scene <span class="text-muted">(you narrate too &mdash; turn it off to stay off camera)</span></label>
    </div>
    <div class="mb-3">
      <label class="form-label small mb-1" for="obs-dm-mic">Your microphone <span class="text-muted">(optional)</span></label>
      <div class="d-flex gap-1 flex-wrap">
        <input type="text" name="obs_dm_mic_label" id="obs-dm-mic" form="obs-cfg-form" class="form-control form-control-sm" value="${cfg.dm_mic_label}" placeholder="leave blank to let vdo.ninja choose">
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="obsListMics(this)" title="Ask this browser for its microphone names and pick one">&#127908; Find mine</button>
      </div>
      <select id="obs-dm-mic-list" class="form-select form-select-sm mt-1" hidden onchange="obsPickMic(this)"></select>
      <div class="form-text small">
        Optional &mdash; leave blank unless the wrong device gets picked. Pins the device on <em>your</em> camera link, matched on its label (the name your browser shows in its mic picker &mdash; <b>&#127908; Find mine</b> lists them for you). Worth setting when this machine also plays the music: some browsers list the same name twice &mdash; once as the microphone, once as <code>Monitor of&hellip;</code> the speakers &mdash; and the monitor would put the music and every player's voice into your own mic channel. Chrome hides those monitors, so <code>${cfg.dm_mic_hint}</code> is unambiguous there.
      </div>
    </div>
    <div class="small fw-bold mt-3 mb-1" style="${SECTION}">Info panel &amp; dice</div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="obs-panel-on" name="obs_panel_on" value="1"${chk(cfg.panel_on === '1')}>
      <label class="form-check-label small" for="obs-panel-on">Show the information panel <span class="text-muted">(falls back to the dice roll feed when there are no notes)</span></label>
    </div>
    <div class="form-check mb-2 ms-3">
      <input class="form-check-input" type="checkbox" id="obs-dice-autohide" name="obs_dice_autohide" value="1"${chk(cfg.dice_autohide === '1')}>
      <label class="form-check-label small" for="obs-dice-autohide">
        Dice as a <b>pop-over</b> <span class="text-muted">(the panel's column is given to the players and the map; the dice fade in over them when a roll lands and fade out 5 seconds later. Notes pin the panel open. Applies to the Party and Map scenes &mdash; <b>rebuild the party scene</b> after changing this, since it changes the layout.)</span>
      </label>
    </div>
    <div class="row g-2 mb-2 ms-3" style="max-width:38rem;">
      <div class="col-4"><label class="form-label small">Panel sits on the</label>
        <select name="obs_panel_side" class="form-select form-select-sm">${['right', 'left', 'top', 'bottom'].map(sd => html`<option value="${sd}"${sel(cfg.panel_side === sd)}>${sd}</option>`)}</select></div>
      <div class="col-4"><label class="form-label small">Share of the canvas</label>
        <input type="number" name="obs_panel_fraction" class="form-control form-control-sm" min="0.12" max="0.6" step="0.02" value="${cfg.panel_fraction}"></div>
      <div class="col-4"><label class="form-label small">Panel refresh (s)</label>
        <input type="number" name="obs_panel_poll_s" class="form-control form-control-sm" min="1" max="60" step="1" value="${cfg.panel_poll}"></div>
    </div>
    <div class="row g-2 mb-2 ms-3" style="max-width:38rem;">
      <div class="col-8"><label class="form-label small">Title</label>
        <input type="text" name="obs_panel_title" class="form-control form-control-sm" maxlength="120" value="${cfg.panel_title}" placeholder="(campaign name)"></div>
      <div class="col-4"><label class="form-label small">Title strip height (px)</label>
        <input type="number" name="obs_title_h" class="form-control form-control-sm" min="0" max="400" step="4" value="${cfg.title_h}">
        <div class="form-text">0 hides it.</div></div>
    </div>
    <div class="mb-3 ms-3" style="max-width:38rem;">
      <label class="form-label small">Panel information &mdash; one line each</label>
      <textarea name="obs_info_text" rows="4" class="form-control form-control-sm" placeholder="Leave empty to stream the dice rolls instead.">${cfg.info_text}</textarea>
      <div class="form-text">
        Shown on stream, so keep secrets in the session's DM notes instead. Empty means the panel scrolls dice rolls as they land. With pop-over dice on, saved text keeps the panel on screen until you clear it. HTML works per line &mdash; e.g. <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, <code>&lt;span style="color:#f5c542"&gt;</code>.
      </div>
      <div class="d-flex flex-wrap gap-2 align-items-center mt-2">
        <select id="obs-note-lib" class="form-select form-select-sm w-auto" style="max-width:15rem;" onchange="obsNoteSelect(this)">
          <option value="">&mdash; saved notes &mdash;</option>
          ${(cfg.panel_notes || []).map(n => html`<option value="${n.id}" data-shared="${n.shared ? '1' : ''}">${n.title}${n.shared ? ' (every session)' : ''}</option>`)}
        </select>
        <button type="button" class="btn btn-outline-light btn-sm" onclick="obsNoteShow()">Show on stream</button>
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="obsNoteSave()">Save text as note&hellip;</button>
        <button type="button" class="btn btn-outline-danger btn-sm" onclick="obsNoteDelete()">Delete</button>
        <label class="form-check-label small"><input class="form-check-input" type="checkbox" id="obs-note-shared"> every session</label>
      </div>
      <div class="form-text">Notes save to the active session; tick <i>every session</i> to keep one in every session's library. Showing a note fills the box above &mdash; edits there change the stream, not the saved note, until you save it again under the same name.</div>
    </div>
    <span class="small text-muted">&#10003; Settings save automatically as you change them. Changing host, port or password reconnects.</span>
  </form>`;
}

function youtubeCard(cfg) {
  const yt = cfg.yt || {};
  const art = (cfg.images || []).find(i => i.slot === 'yt_thumb') || {};
  return html`<div class="ttrpg-card p-3 mb-3">
    <h6 style="${H6}" class="mb-2">&#128250; Go Live &mdash; YouTube</h6>
    <p class="small text-muted">
      Set tonight's stream info here and go live without touching the streaming machine: ScenePlay creates the YouTube broadcast with everything below, points OBS at it, and starts streaming. The stream goes live on YouTube as soon as OBS's feed arrives, and stopping the stream (&#9632; up top, or in OBS) ends the broadcast automatically.
    </p>
    <div class="row g-2 mb-2">
      <div class="col-sm-7"><label class="form-label small">Google OAuth client ID</label>
        <input name="yt_client_id" form="obs-cfg-form" class="form-control form-control-sm" value="${yt.client_id}" placeholder="&hellip;.apps.googleusercontent.com"></div>
      <div class="col-sm-5"><label class="form-label small">Client secret ${yt.has_secret ? html`<span class="text-muted">(saved &mdash; blank keeps it)</span>` : ''}</label>
        <input type="password" name="yt_client_secret" form="obs-cfg-form" class="form-control form-control-sm" autocomplete="new-password" placeholder="${yt.has_secret ? '••••••••' : ''}"></div>
    </div>
    <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
      ${yt.linked ? html`<span class="small">&#10003; Linked${yt.channel ? html` as <b>${yt.channel}</b>` : ''}</span>
        <button type="button" class="btn btn-sm btn-outline-danger" onclick="obsYtUnlink(this)">Unlink</button>`
    : html`<button type="button" class="btn btn-sm btn-ttrpg" onclick="obsYtLink(this)">&#128279; Link YouTube</button>`}
      <span id="obs-yt-link-msg" class="small"></span>
    </div>
    <div class="form-text mb-3">
      One-time setup: in Google Cloud Console create a project, enable the <b>YouTube Data API v3</b>, and create an OAuth client of type <b>TVs and Limited Input devices</b>; paste its ID and secret above, then Link &mdash; you'll type a short code at google.com/device. Publish the consent screen to <i>In production</i>, or Google expires the link every 7 days.
    </div>
    <div class="row g-2 mb-2">
      <div class="col-sm-8"><label class="form-label small">Stream title</label>
        <input name="yt_title" form="obs-cfg-form" maxlength="100" class="form-control form-control-sm" value="${yt.title}" placeholder="(tonight's campaign or session name)"></div>
      <div class="col-sm-4"><label class="form-label small">Privacy</label>
        <select name="yt_privacy" form="obs-cfg-form" class="form-select form-select-sm">${(yt.privacies || []).map(p => html`<option value="${p}"${sel(yt.privacy === p)}>${p}</option>`)}</select></div>
    </div>
    <div class="mb-2"><label class="form-label small">Description</label>
      <textarea name="yt_description" form="obs-cfg-form" rows="3" class="form-control form-control-sm" placeholder="(shown under the video)">${yt.description}</textarea></div>
    <div class="row g-2 mb-2 align-items-end">
      <div class="col-sm-5"><label class="form-label small">Category</label>
        <select name="yt_category" form="obs-cfg-form" class="form-select form-select-sm">${(yt.categories || []).map(([cid, cname]) => html`<option value="${cid}"${sel(yt.category === cid)}>${cname}</option>`)}</select></div>
      <div class="col-sm-7">
        <div class="form-check mb-1">
          <input class="form-check-input" type="checkbox" id="obs-yt-kids" name="yt_kids" value="1" form="obs-cfg-form"${chk(yt.kids)}>
          <label class="form-check-label small" for="obs-yt-kids">Made for kids <span class="text-muted">&mdash; YouTube's COPPA declaration</span></label>
        </div>
      </div>
    </div>
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
      ${artWell(art, 66, 38, 5, false)}
      <div class="small text-muted" style="font-size:.7rem;min-width:7rem;flex:1 1 auto;">
        Thumbnail &mdash; 1280&times;720 JPG/PNG under 2&nbsp;MB
        <div>${art.file ? html`<code>${art.file}</code>` : 'not set'}</div>
      </div>
      <form method="post" enctype="multipart/form-data" action="/ttrpg/obs/image/yt_thumb" data-api="/ttrpg/obs/image/yt_thumb" data-multipart="1" class="d-flex align-items-center gap-1" style="margin:0;">
        <input type="file" name="image" accept="image/jpeg,image/png" class="form-control form-control-sm" style="max-width:12rem;" onchange="if (this.files.length) _obsSubmitForm(this.form);">
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="obsReuseArt(this.form, ['image'])" title="Reuse a picture already on this server — nothing is copied">&#128444;</button>
        <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0" onclick="pasteImageNear(this)" title="Paste an image from the clipboard">&#128203;</button>
      </form>
      ${art.file ? html`<form method="post" action="/ttrpg/obs/image/yt_thumb" data-api="/ttrpg/obs/image/yt_thumb" data-multipart="1" style="margin:0;"><button name="clear" value="1" class="btn btn-sm btn-outline-danger">Clear</button></form>` : ''}
    </div>
    <div class="d-flex align-items-center gap-2 flex-wrap">
      <button type="button" class="btn btn-sm btn-ttrpg" onclick="obsYtGoLive(this)"${yt.linked ? '' : raw(' disabled title="Link YouTube first"')}>&#9654; Go live on YouTube</button>
      <span id="obs-yt-live-msg" class="small"></span>
    </div>
  </div>`;
}

export function render(d) {
  const cfg = d.cfg, snap = d.snap;
  const on = s => s === snap.current_scene;
  return html`<div class="row justify-content-center"><div class="col-lg-8">

    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 style="${H6}" class="mb-0">&#127909; Broadcast (OBS)</h4>
      <a href="/ttrpg/obs" class="btn btn-sm btn-outline-secondary">&#8635; Refresh</a>
    </div>

    ${cfg.boot_tripped ? html`<div class="alert mb-3" style="${ALERT_RED}">
      &#9888; OBS control was <strong>automatically disabled</strong> on ${cfg.boot_tripped}: the previous app start crashed while connecting to OBS. Enable it again below when you're ready &mdash; re-enabling clears this notice.
    </div>` : ''}

    <!-- Status -->
    <div class="ttrpg-card p-3 mb-3">
      <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div>
          <span class="fw-bold">Status:</span>
          <span class="badge ms-1" id="obs-state-badge">…</span>
          <span class="small text-muted ms-2" id="obs-version-line">${snap.obs_version ? `OBS ${snap.obs_version}` : ''} ${snap.ws_version ? raw(`&middot; obs-websocket ${snap.ws_version}`) : ''}</span>
        </div>
        <form method="post" action="/ttrpg/obs/toggle" data-api="/ttrpg/obs/toggle">
          <button class="btn btn-sm ${cfg.enabled === '1' ? 'btn-outline-danger' : 'btn-ttrpg'}">${cfg.enabled === '1' ? 'Disable' : 'Enable'} OBS Control</button>
        </form>
      </div>
      <div class="mt-2 small">
        <span class="text-muted">Live scene:</span>
        <strong style="${H6}" id="obs-current-scene">${snap.current_scene || '—'}</strong>
        <span class="badge bg-danger ms-2" id="obs-rec-pill" style="display:${snap.recording ? 'inline-block' : 'none'};">&#9679; REC</span>
        <span class="badge bg-primary ms-1" id="obs-live-pill" style="display:${snap.streaming ? 'inline-block' : 'none'};">LIVE</span>
      </div>
      <div class="mt-2 d-flex flex-wrap gap-2">
        <button id="obs-record-btn" class="btn btn-sm btn-outline-danger" onclick="obsOutput('record', this)" disabled>&#9679; Start recording</button>
        <button id="obs-stream-btn" class="btn btn-sm btn-outline-primary" onclick="obsOutput('stream', this)" disabled>&#9654; Start streaming</button>
        <span class="small text-muted align-self-center" id="obs-output-note"></span>
      </div>
      <div id="obs-problems" class="mt-2 small" style="color:#e09090;">${(d.problems || []).map(p => html`<div>&#9888; ${p}</div>`)}</div>
      ${cfg.last_error ? html`<div class="mt-2 small text-muted">Last error: ${cfg.last_error}</div>` : ''}
    </div>

    <!-- Manual switch -->
    <div class="ttrpg-card p-3 mb-3">
      <h6 style="${H6}" class="mb-2">All Scenes</h6>
      <div id="obs-scene-buttons" class="d-flex flex-wrap gap-2">
        ${snap.scenes.length ? snap.scenes.map(s => html`<button class="btn btn-sm obs-scene-btn" data-scene="${s}" onclick="obsSwitchScene(this)"
            style="background:${on(s) ? 'var(--ttrpg-accent);color:var(--sp-on-accent)' : 'var(--ttrpg-surface);color:var(--ttrpg-text)'};border:1px solid ${on(s) ? 'var(--ttrpg-accent)' : 'var(--sp-border)'};">${s}</button>`)
    : html`<span class="small text-muted">No scenes yet &mdash; connect to OBS first.</span>`}
      </div>
    </div>

    <!-- Party scene -->
    <div class="ttrpg-card p-3 mb-3">
      <div class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2">
        <h6 style="${H6}" class="mb-0">Party Scene</h6>
        <div class="d-flex gap-2 flex-wrap">
          <button class="btn btn-sm btn-ttrpg" onclick="obsBuildParty(this)" title="Create or refresh the OBS scene holding every player">&#9635; Build / refresh party scene</button>
          <button class="btn btn-sm btn-outline-secondary" onclick="obsRefreshScenes(this)">&#8635; Re-read from OBS</button>
        </div>
      </div>
      <div id="obs-build-report" class="small mb-2" hidden></div>
      <p class="small text-muted">
        Everyone lives in one OBS scene as a tile. Giving a player the turn <b>spotlights</b> them &mdash; their tile grows to double size and the rest shrink and repack around it, easing across rather than jumping. The whole table stays on screen and nobody gets covered, so it reads as "listen to this one" for an important piece of dialog. Players with no camera get a stat card instead of an empty box.
      </p>
      ${!d.has_party ? html`<p class="small text-muted mb-0">No active session &mdash; start a session and add a party first.</p>` : html`
      <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
        <span class="small text-muted">Stream audio:</span>
        <button type="button" class="btn btn-sm btn-outline-danger" onclick="obsMuteAll('everyone', true)" title="Silence the whole table on the stream — you included. The room keeps talking; the broadcast goes quiet.">&#128263; Mute everyone</button>
        <button type="button" class="btn btn-sm btn-outline-danger" onclick="obsMuteAll('players', true)" title="Mute every player's voice on the stream — your own tile is left alone">&#128263; Mute players</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="obsMuteAll('everyone', false)" title="Unmute the whole table on the stream">&#128266; Unmute all</button>
        <span class="small text-muted">Mutes survive rebuilds; each row's speaker toggles one voice. Scenes can flip these automatically &mdash; see Scene Links.</span>
      </div>
      <div id="obs-rows">${d.rows.map(r => partyRow(r, d))}</div>
      <p class="small text-muted mt-2 mb-0">
        The leftmost tick is who's <b>on the group feed</b>. Untick someone sitting this episode out, or the half of a split party the stream isn't following &mdash; they keep their seat in the session and everything on their sheet, the grid just re-lays-out without them until you tick them back. The dot shows whether a player has a camera feed set (and, for remote players, whether they're online). Use &#9650;&#9660; to set the turn order &mdash; that's also the order the number keys 1&ndash;9 follow (0 or G for the group shot, &#9664;&#9654; to step through the party).
      </p>
      <div class="row g-2 align-items-end mt-2" style="max-width:32rem;">
        <div class="col-5">
          <label class="form-label small mb-1" for="obs-tile-anim">Spotlight glide (ms)</label>
          <input type="number" id="obs-tile-anim" name="obs_tile_anim_ms" form="obs-cfg-form" class="form-control form-control-sm" min="0" max="4000" step="50" value="${cfg.tile_anim_ms}">
        </div>
        <div class="col-7 small text-muted" style="padding-bottom:.4rem;">How long the tiles take to resize when the spotlight moves to a player and when <b>0</b>/<b>G</b> evens the table out again. <b>0</b> snaps instantly. Saves automatically.</div>
      </div>
      ${streamLook(cfg)}
      ${cfg.portal_url ? html`<div class="small text-muted mt-2 d-flex align-items-center gap-2 flex-wrap">
        <span>Remote players log in at</span> <code>${cfg.portal_url}</code>
        <a href="${cfg.portal_url}" target="_blank" rel="noopener" data-native class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size:.7rem;">open</a>
        <span>&mdash; their camera link is waiting there. The &#128247; button on a player's row has a QR code to send them.</span>
      </div>` : ''}`}
    </div>

    ${showArt(cfg)}
    ${mapCard(cfg, d)}
    ${sceneLinks(d)}

    <!-- Connection settings -->
    <div class="ttrpg-card p-3 mb-3">
      <div class="d-flex align-items-center justify-content-between mb-3"><h6 style="${H6}" class="mb-0">Connection Settings</h6></div>
      ${(d.obs_servers || []).length ? html`<div class="mb-2">
        <label class="form-label small">OBS found on your network</label>
        <select id="obs-host-pick" class="form-select form-select-sm" onchange="obsPickHost(this)">
          <option value="">&mdash; choose a scanned server &mdash;</option>
          ${d.obs_servers.map(s => html`<option value="${s.ip}"${sel(s.ip === cfg.host)}>${s.name} (${s.ip})</option>`)}
        </select>
        <div class="form-text">From the network scan on the Servers page. Picking one fills the host below; save to apply.</div>
      </div>` : ''}
      <div class="row g-2 mb-2">
        <div class="col-sm-8"><label class="form-label small">OBS host</label>
          <input type="text" name="obs_host" id="obs-host-input" form="obs-cfg-form" class="form-control form-control-sm" placeholder="127.0.0.1" value="${cfg.host}"></div>
        <div class="col-sm-4"><label class="form-label small">Port</label>
          <input type="number" name="obs_port" id="obs-port-input" form="obs-cfg-form" class="form-control form-control-sm" min="1" max="65535" value="${cfg.port}"></div>
      </div>
      <div class="mb-3">
        <label class="form-label small">WebSocket password</label>
        <input type="password" name="obs_password" form="obs-cfg-form" class="form-control form-control-sm" placeholder="${cfg.has_password ? 'leave blank to keep existing' : 'from OBS → Tools → WebSocket Server Settings'}" value="" autocomplete="new-password">
      </div>
      ${rigCard(cfg)}
      ${pageAddressCard(cfg)}
      ${settingsForm(cfg, d)}
      <form method="post" action="/ttrpg/obs/api/theme-shared" data-api="/ttrpg/obs/api/theme-shared" id="obs-theme-shared-form"></form>
      ${['title', 'intermission', 'post'].map(slot => html`<form method="post" enctype="multipart/form-data" action="/ttrpg/obs/image/${slot}" data-api="/ttrpg/obs/image/${slot}" data-multipart="1" id="obs-art-${slot}"></form>`)}
      <hr style="border-color:var(--sp-border);">
      <p class="small text-muted mb-0">
        In OBS: <b>Tools &rarr; WebSocket Server Settings</b> &rarr; tick <i>Enable WebSocket server</i>, then <i>Show Connect Info</i> for the port and password. If OBS runs on this same machine, leave the host at 127.0.0.1.
      </p>
    </div>

    ${youtubeCard(cfg)}

  </div></div>`;
}

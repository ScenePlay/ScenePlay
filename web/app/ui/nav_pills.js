// Relay / OBS / LED-remote / WLED status pills (from store.health).
import { html, raw } from '../lib/dom.js';

export function pillsHtml(h, { dmOnly = false, isDm = false } = {}) {
  if (!h || (dmOnly && !isDm)) return raw('');
  const parts = [];
  if (h.relay && h.relay.on) {
    const color = h.relay.failing ? '#dc3545' : (h.relay.stale ? '#e0a800' : '#28a745');
    const title = h.relay.failing ? `Relay UNREACHABLE — API pushes are failing (${h.relay.msg}). Scene switches will lag; disable the relay if you're not using it.`
      : (h.relay.stale ? 'Relay is enabled but not syncing — click to manage' : 'Remote-play relay is running — click to manage');
    parts.push(html`<a href="/ttrpg/relay/" class="nav-link sp-status-pill" style="--pill: ${color};" title="${title}"><span class="sp-status-dot"></span>${h.relay.failing ? raw('<span data-sp-alert="1">Relay&nbsp;FAILING</span>') : raw('Relay&nbsp;ON')}</a>`);
  }
  if (h.obs && h.obs.on) {
    parts.push(html`<a href="/ttrpg/obs/" class="nav-link sp-status-pill" style="--pill: ${h.obs.connected ? '#28a745' : '#e0a800'};" title="${h.obs.connected ? 'OBS is connected — click for the Broadcast console' : 'OBS integration is enabled but OBS is not connected — launch OBS, or check the host/port on the Broadcast page'}"><span class="sp-status-dot"></span>${h.obs.connected ? raw('OBS&nbsp;ON') : raw('OBS&nbsp;OFFLINE')}</a>`);
  }
  if (h.led_remote && h.led_remote.failing) {
    parts.push(html`<a href="/serverIP" class="nav-link sp-status-pill" style="--pill: #dc3545;" data-sp-alert="1" title="LED transfer to a Remote ScenePlay box is failing (${h.led_remote.msg}). Every scene switch waits on its timeout — deactivate the dead server row to clear this."><span class="sp-status-dot"></span>LED&nbsp;Remote&nbsp;FAILING</a>`);
  }
  if (h.wled && h.wled.failing) {
    parts.push(html`<a href="/serverIP" class="nav-link sp-status-pill" style="--pill: #dc3545;" data-sp-alert="1" title="WLED lighting commands are failing (${h.wled.msg}). Scene switches wait on its timeout — deactivate the dead board's server row to clear this."><span class="sp-status-dot"></span>WLED&nbsp;FAILING</a>`);
  }
  return raw(parts.map(String).join(''));
}

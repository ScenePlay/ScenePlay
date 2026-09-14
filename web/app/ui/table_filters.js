// Campaign / scene filter row shared by the table pages (site.js
// campaignFilterChange / sceneFilterChange / applyFilterResponse).
import { html, render } from '../lib/dom.js';
import { api } from '../api.js';

export function filtersHtml(f, { campaign = true, scene = true } = {}) {
  return html`<div class="sp-filter-row">
    ${campaign ? html`<label for="campaignFilterDropdown">Filter By Campaign</label>
      <select id="campaignFilterDropdown" class="form-select"><option value="0">All</option>
        ${(f.campaigns || []).map(c => html`<option value="${c[0]}" ${c[0] === f.campaignFilter ? 'selected' : ''}>${c[1]}</option>`)}</select>` : ''}
    ${scene ? html`<label for="editSceneDropdown">Filter By Scene</label>
      <select id="editSceneDropdown" class="form-select"><option value="0">All</option>
        ${(f.scenes || []).map(s => html`<option value="${s[0]}" ${s[0] === f.sceneFilter ? 'selected' : ''}>${s[1]}</option>`)}</select>` : ''}
  </div>`;
}

export function applyFilterResponse(root, resp, sceneValue) {
  const camp = root.querySelector('#campaignFilterDropdown');
  if (camp) camp.value = String(resp.campaign_id);
  const sc = root.querySelector('#editSceneDropdown');
  if (sc) {
    sc.innerHTML = '';
    const all = document.createElement('option'); all.value = '0'; all.textContent = 'All'; sc.appendChild(all);
    (resp.scenes || []).forEach(s => { const o = document.createElement('option'); o.value = String(s[0]); o.textContent = s[1]; sc.appendChild(o); });
    sc.value = sceneValue;
    if (sc.selectedIndex === -1) sc.value = '0';
  }
}

export function wireFilters(root, ctx, onChange) {
  const camp = root.querySelector('#campaignFilterDropdown'), sc = root.querySelector('#editSceneDropdown');
  if (camp) ctx.on(camp, 'change', async e => {
    const resp = await api.post('/api/campaignFilter', { campaign_id: e.target.value });
    applyFilterResponse(root, resp, '0'); onChange();
  });
  if (sc) ctx.on(sc, 'change', async e => {
    const v = String(e.target.value);
    const resp = await api.post('/api/sceneFilter', { scene_id: v });
    applyFilterResponse(root, resp, v); onChange();
  });
}

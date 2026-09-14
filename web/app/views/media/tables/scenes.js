import { YES_NO, CAMPAIGN_LOOKUP } from './_common.js';
import { esc } from '../../../lib/dom.js';
import { openSmartSceneForm } from './smart_scene_modal.js';

export default {
  id: 'scenes', title: 'Scenes Table', primeKey: 'scene_ID',
  endpoints: { list: '/api/scenes', update: '/api/scenes', add: '/api/scenesaddrow', del: '/api/scenesdelrow' },
  filters: { campaign: true, scene: true },
  addRow: { field: 'campaign_id', kind: 'campaign', dropdownId: 'campaignFilterDropdown', confirmSkip: true },
  lookups: { campaigns: CAMPAIGN_LOOKUP },
  cells: [
    { id: 'scene_ID', hidden: true },
    { id: 'sceneName', name: 'Scene Name', cell: 'text' },
    { id: 'active', name: 'isActive', cell: 'select', options: YES_NO },
    { id: 'orderBy', name: 'Order', cell: 'text' },
    { id: 'campaign_id', name: 'Campaign', cell: 'select', lookup: 'campaigns' },
    { id: 'rule', name: 'Rule', sort: false, cell: 'html', render: (rule, row, h) => rule ? `<span class="small" title="This scene fills itself from this rule">&#9889; ${esc(rule)}</span> <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size:.7rem;" data-unlink="${h.rowId}" title="Stop deriving — keep the scene and its songs as they are">&#10005; unlink</button>` : '' },
    { cell: 'check' },
  ],
  toolbar: [{ label: '+ Smart Scene', onClick: (ctx, api) => openSmartSceneForm(() => window.spGrid && window.spGrid.forceRender()) }],
  onClick(ev, { reload, api }) {
    const b = ev.target.closest && ev.target.closest('button[data-unlink]');
    if (!b) return;
    if (!confirm('Stop deriving this scene from its rule? The scene and everything in it stay.')) return;
    api.post('/api/scenes/unlink-rule', { scene_ID: Number(b.dataset.unlink) }).then(reload);
  },
};

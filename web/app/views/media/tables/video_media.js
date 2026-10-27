import { YES_NO, SCENE_ADDROW } from './_common.js';
import { spPickOption } from '../../../ui/pick_option.js';
import { toast } from '../../../ui/toast.js';
export default {
  id: 'videomedia', title: 'Video Media Table', primeKey: 'video_ID',
  endpoints: { list: '/api/videomedia', update: '/api/videomedia', add: '/api/videomediaaddrow', del: '/api/videomediadelrow' },
  filters: { campaign: true, scene: true }, addRow: SCENE_ADDROW,
  lookups: { status: { url: '/api/dnLoadStatus', id: 'status_ID', label: 'status' } },
  cells: [
    { id: 'video_ID', hidden: true },
    { id: 'path', name: 'Path', width: '210px' },
    { id: 'title', name: 'Name', cell: 'nameWithMeta', from: 'displayName', width: '300px' },
    { id: 'pTimes', name: 'Played Times', width: '170px' },
    { id: 'playedDTTM', name: 'Played DTTM', width: '170px' },
    { id: 'active', name: 'Active', hidden: true },
    { id: 'genre', name: 'Genre', hidden: true, sort: false },
    { id: 'que', name: 'Queued', cell: 'select', options: YES_NO, width: '130px' },
    { id: 'urlSource', name: 'URL Source', cell: 'link', sort: false, width: '140px' },
    { id: 'dnLoadStatus', name: 'Download Status', cell: 'badge', lookup: 'status', blank: true, errorFrom: 'dnLastError', width: '200px' },
    { id: 'duration', name: 'Length', cell: 'duration', width: '110px' },
    { id: 'uploader', name: 'Uploader', width: '180px' },
    { id: 'thumbnail', name: 'Info', cell: 'thumbInfo', mediaType: 'video', sort: false, width: '130px' },
    { id: 'mapbg', name: 'Map', sort: false, width: '70px', cell: 'html', render: (v, row, h) => `<button type="button" class="btn btn-sm btn-outline-secondary" title="Use this video as a battle map background" data-mapbg="${h.rowId}">\u{1F5FA}</button>` },
    { cell: 'check' },
    { id: 'dnLastError', hidden: true },
    { id: 'displayName', hidden: true },
  ],
  async onClick(ev, { api }) {
    const b = ev.target.closest && ev.target.closest('button[data-mapbg]');
    if (!b) return;
    let maps;
    try { maps = await api.get('/ttrpg/battlemap/api/maps', { quiet: true }); } catch (e) { toast.warn('Log in as the DM first (TTRPG login), then try again.'); return; }
    if (!maps || !maps.length) { toast.warn('No battle maps yet — create one in the TTRPG map manager first.'); return; }
    const picked = await spPickOption('Use video as background', 'Use this video as the background for which map?', 'Map', maps.map(m => ({ value: m.map_id, label: m.session + ' / ' + m.name })), 'Set Background');
    if (picked === null) return;
    try {
      const out = await api.post('/ttrpg/battlemap/' + picked + '/bg-from-library', { video_ID: Number(b.dataset.mapbg) }, { quiet: true });
      if (out.ok) toast.success('Background set on "' + out.map + '".'); else toast.error('Failed: ' + (out.error || 'unknown error'));
    } catch (e) { toast.error('Failed: ' + e.message); }
  },
};

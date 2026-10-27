import { SCENE_LOOKUP, SCENE_ADDROW } from './_common.js';
export default {
  id: 'videoScene', title: 'Video Scene Table', primeKey: 'videoScene_ID',
  endpoints: { list: '/api/videoScene', update: '/api/videoScene', add: '/api/videoSceneaddrow', del: '/api/videoScenedelrow' },
  filters: { campaign: true, scene: true }, addRow: SCENE_ADDROW,
  lookups: { scenes: SCENE_LOOKUP, videos: { url: '/api/videomedia', id: 'video_ID', label: r => r.displayName || r.title, lazy: true } },
  cells: [
    { id: 'videoScene_ID', hidden: true },
    { id: 'scene_ID', name: 'Scenes', cell: 'select', lookup: 'scenes', lazy: true },   // sortable, as in 1.x
    { id: 'video_ID', name: 'Video', cell: 'mediaPicker', lookup: 'videos', sort: false, width: '36%' },
    { id: 'DisplayScreen_ID', name: 'Screen', cell: 'text', sort: false },
    { id: 'orderBy', name: 'orderBy', cell: 'text' },
    { id: 'volume', name: 'Volume 0-100', cell: 'text', sort: false },
    { id: 'loops', name: 'Loops 0-9999', cell: 'text', sort: false },
    { cell: 'check' },
  ],
};

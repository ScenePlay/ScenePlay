import { SCENE_LOOKUP, SCENE_ADDROW } from './_common.js';
export default {
  id: 'musicScene', title: 'Music Scene Table', primeKey: 'musicScene_ID',
  endpoints: { list: '/api/musicScene', update: '/api/musicScene', add: '/api/musicSceneaddrow', del: '/api/musicScenedelrow' },
  filters: { campaign: true, scene: true }, addRow: SCENE_ADDROW,
  lookups: { scenes: SCENE_LOOKUP, songs: { url: '/api/music', id: 'song_ID', label: r => r.displayName || r.song, lazy: true } },
  cells: [
    { id: 'musicScene_ID', hidden: true },
    { id: 'scene_ID', name: 'Scenes', cell: 'select', lookup: 'scenes', lazy: true, sort: false },
    { id: 'song_ID', name: 'Song', cell: 'mediaPicker', lookup: 'songs', sort: false, width: '36%' },
    { id: 'orderBy', name: 'orderBy', cell: 'text' },
    { id: 'volume', name: 'Volume 0-100', cell: 'text', sort: false },
    { id: 'loops', name: 'Loops 0-9999', cell: 'text', sort: false },
    { cell: 'check' },
  ],
};

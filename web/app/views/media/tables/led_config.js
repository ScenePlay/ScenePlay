// LED Config Table (templates/ledConfig_table.html): the Pi's strip rows —
// pin, LED count, hardware brightness cap, active. Saves go to
// /api/ledconfigsave; there was never an add endpoint (rows are seeded).
import { YES_NO } from './_common.js';
export default {
  id: 'ledconfig', title: 'LED Config Table', primeKey: 'ledConfig_ID',
  endpoints: { list: '/api/ledconfig', update: '/api/ledconfigsave', del: '/api/ledconfigdelrow' },
  cells: [
    { id: 'ledConfig_ID', hidden: true },
    { id: 'pin', name: 'Raspi Pin', sort: false },
    { id: 'ledCount', name: 'LED Count', cell: 'text', sort: false },
    { id: 'brightness', name: 'Max brightness 0.0–1.0 (hardware cap — lower it until colors stay true at the far end of the strip)', cell: 'text', sort: false },
    { id: 'active', name: 'Active', cell: 'select', options: YES_NO, sort: false },
    { cell: 'check' },
  ],
};

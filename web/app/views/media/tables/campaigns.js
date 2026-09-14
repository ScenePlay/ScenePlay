import { YES_NO } from './_common.js';
export default {
  id: 'campaigns', title: 'Campaign Table', primeKey: 'campaign_id',
  endpoints: { list: '/api/campaigns', update: '/api/campaigns', add: '/api/campaignaddrow', del: '/api/campaigndelrow' },
  cells: [
    { id: 'campaign_id', hidden: true },
    { id: 'campaign_name', name: 'Campaign', cell: 'text' },
    { id: 'active', name: 'Active', cell: 'select', options: YES_NO, sort: false },
    { id: 'order_by', name: 'Order', cell: 'text' },
    { cell: 'check' },
  ],
};

export const YES_NO = [{ value: '1', label: 'Yes' }, { value: '0', label: 'No' }];
export const SCENE_LOOKUP = { url: '/api/scenes', id: 'scene_ID', label: 'sceneName', lazy: true };
export const CAMPAIGN_LOOKUP = { url: '/api/campaigns', id: 'campaign_id', label: 'campaign_name' };
export const SCENE_ADDROW = { field: 'scene_ID', kind: 'scene', dropdownId: 'editSceneDropdown', contextDropdownId: 'campaignFilterDropdown', contextKind: 'campaign' };

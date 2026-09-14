import * as auth from '../../auth.js';
export async function mount(outlet, ctx) { auth.logout(); }

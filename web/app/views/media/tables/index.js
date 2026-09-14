// Generic table page: picks the config module by route prop.
import { mountTable } from '../../../ui/table_editor.js';

const CONFIGS = {
  campaigns: () => import('./campaigns.js'),
  scenes: () => import('./scenes.js'),
  scene_pattern: () => import('./scene_pattern.js'),
  wled_pattern: () => import('./wled_pattern.js'),
  music_scene: () => import('./music_scene.js'),
  video_scene: () => import('./video_scene.js'),
  music_media: () => import('./music_media.js'),
  video_media: () => import('./video_media.js'),
  led_config: () => import('./led_config.js'),
  server_ip: () => import('./server_ip.js'),
  cron_schedule: () => import('./cron_schedule.js'),
};

export function title(ctx) { return (ctx.route.props && ctx.route.props.table || 'table').replace('_', ' '); }

export async function mount(outlet, ctx) {
  const name = ctx.route.props.table;
  const loader = CONFIGS[name];
  if (!loader) { outlet.innerHTML = '<div class="alert alert-warning m-3">Unknown table.</div>'; return; }
  const mod = await loader();
  document.title = mod.default.title + ' — ScenePlay';
  await mountTable(outlet, ctx, mod.default);
}

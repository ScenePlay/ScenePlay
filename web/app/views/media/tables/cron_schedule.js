// Cron Schedules (templates/cronSchedule_table.html): the plain-language
// schedule wizard (POST /api/cronwizard builds the command + cron fields,
// saves the row active and applies the scheduler) above the raw table —
// the power-user view for custom commands and exotic cron patterns.
import { YES_NO } from './_common.js';
import { esc } from '../../../lib/dom.js';
import { api } from '../../../api.js';
import { toast } from '../../../ui/toast.js';

const WIZ_ACTION_LABELS = {
  scene: s => "activate scene '" + s + "'",
  allstop: () => 'stop all music and video',
  volume: v => 'set volume to ' + (v || '?') + '%',
  repeat_on: () => 'turn music repeat ON',
  repeat_off: () => 'turn music repeat OFF',
  reboot: () => 'restart the computer',
  update: () => 'update ScenePlay and restart',
};
const WIZ_DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DAY_BOXES = [['0', 'Su'], ['1', 'Mo'], ['2', 'Tu'], ['3', 'We'], ['4', 'Th'], ['5', 'Fr'], ['6', 'Sa']];

const WIZARD = `<div id="cronWizard" style="border:1px solid var(--sp-border);border-radius:8px;padding:14px 16px;margin:0 0 14px;background:var(--sp-surface);max-width:900px;">
  <h4 style="margin:0 0 10px;">&#10024; New Schedule</h4>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px;">
    <b>1. What?</b>
    <select id="wiz-action" class="form-select form-select-sm" style="width:auto;">
      <option value="scene">Activate a scene</option>
      <option value="allstop">All Stop — silence everything</option>
      <option value="volume">Set the volume</option>
      <option value="repeat_on">Music repeat ON</option>
      <option value="repeat_off">Music repeat OFF</option>
      <option value="reboot">Restart the computer</option>
      <option value="update">Update ScenePlay &amp; restart</option>
    </select>
    <select id="wiz-scene" class="form-select form-select-sm" style="width:auto;"></select>
    <span id="wiz-volume-wrap" style="display:none;">
      <input type="number" id="wiz-volume" value="50" min="0" max="100" class="form-control form-control-sm" style="width:80px;display:inline-block;"> %
    </span>
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px;">
    <b>2. When?</b>
    <input type="time" id="wiz-time" value="18:00" class="form-control form-control-sm" style="width:auto;">
    <span>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-wiz-days="0,1,2,3,4,5,6">Every day</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-wiz-days="1,2,3,4,5">Weekdays</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" data-wiz-days="0,6">Weekends</button>
    </span>
    <span id="wiz-day-boxes" style="white-space:nowrap;">
      ${DAY_BOXES.map(([v, l]) => `<label style="margin-right:6px;"><input type="checkbox" class="wiz-day" value="${v}" checked> ${l}</label>`).join('')}
    </span>
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
    <b>3. Name</b>
    <input type="text" id="wiz-name" placeholder="(optional — auto-named)" class="form-control form-control-sm" style="width:240px;">
    <button type="button" class="btn btn-success btn-sm" id="wiz-save">Save &amp; Apply</button>
    <span id="wiz-preview" style="color:var(--sp-muted);font-style:italic;"></span>
  </div>
  <div id="wiz-msg" style="margin-top:8px;"></div>
</div>`;

export default {
  id: 'cronSchedule', title: 'Cron Schedules', primeKey: 'schedule_id',
  endpoints: { list: '/api/cronSchedule', update: '/api/cronSchedule', add: '/api/cronscheduleaddrow', del: '/api/cronscheduledelrow' },
  cells: [
    { id: 'schedule_id', hidden: true },
    { id: 'name', name: 'Name', cell: 'text' },
    { id: 'minute', name: 'Minute', cell: 'text', sort: false },
    { id: 'hour', name: 'Hour', cell: 'text', sort: false },
    { id: 'day_of_month', name: 'Day of Month', cell: 'text', sort: false },
    { id: 'month', name: 'Month', cell: 'text', sort: false },
    { id: 'day_of_week', name: 'Day of Week', cell: 'text', sort: false },
    { id: 'command', name: 'Command', cell: 'text', sort: false },
    { id: 'description', name: 'Description', cell: 'text', sort: false },
    { id: 'active', name: 'Active', cell: 'select', options: YES_NO, sort: false },
    { cell: 'check' },
  ],
  toolbar: [{
    label: 'Apply to Crontab', className: 'btn btn-success',
    async onClick(ctx, api) {
      if (!confirm('Apply all active schedules to the system crontab? Existing ScenePlay-managed entries will be replaced.')) return;
      try {
        const r = await api.post('/api/applycronschedules', {}, { quiet: true });
        if (r.success) toast.success('Crontab updated successfully. ' + r.count + ' active schedule(s) applied.' + (r.dry_run ? ' (dry run — SP_CRON_APPLY=0)' : ''));
        else toast.error('Failed to update crontab: ' + (r.error || 'Unknown error'));
      } catch (e) { toast.error('Failed to update crontab: ' + e.message); }
    },
  }],
  async extras(ctx, { reload, outlet }) {
    const scroll = outlet.querySelector('.sp-table-scroll');
    scroll.insertAdjacentHTML('beforebegin', WIZARD);
    const card = outlet.querySelector('#cronWizard');
    const $ = id => card.querySelector('#' + id);
    const sceneSel = $('wiz-scene');

    const selectedDays = () => [...card.querySelectorAll('.wiz-day:checked')].map(cb => parseInt(cb.value, 10));
    const preview = () => {
      const a = $('wiz-action').value;
      const sceneName = sceneSel.options[sceneSel.selectedIndex] ? sceneSel.options[sceneSel.selectedIndex].text : '?';
      const days = selectedDays();
      const t = $('wiz-time').value || '18:00';
      let when;
      if (days.length === 7) when = 'Every day';
      else if (days.join() === '1,2,3,4,5') when = 'Weekdays';
      else if (days.join() === '0,6') when = 'Weekends';
      else if (days.length === 0) when = '(pick at least one day)';
      else when = days.map(d => WIZ_DAY_SHORT[d]).join(', ');
      const [h, m] = t.split(':').map(Number);
      const ampm = ((h % 12) || 12) + ':' + String(m).padStart(2, '0') + ' ' + (h >= 12 ? 'PM' : 'AM');
      const label = WIZ_ACTION_LABELS[a](a === 'volume' ? $('wiz-volume').value : sceneName);
      $('wiz-preview').textContent = when + ' at ' + ampm + ' — ' + label;
    };
    const actionChange = () => {
      const a = $('wiz-action').value;
      sceneSel.style.display = a === 'scene' ? '' : 'none';
      $('wiz-volume-wrap').style.display = a === 'volume' ? '' : 'none';
      preview();
    };

    ctx.on($('wiz-action'), 'change', actionChange);
    ctx.on(card, 'change', preview);
    ctx.on(card, 'input', ev => { if (ev.target.id === 'wiz-volume') preview(); });
    ctx.on(card, 'click', ev => {
      const b = ev.target.closest && ev.target.closest('button[data-wiz-days]');
      if (!b) return;
      const days = b.dataset.wizDays.split(',').map(Number);
      card.querySelectorAll('.wiz-day').forEach(cb => { cb.checked = days.includes(parseInt(cb.value, 10)); });
      preview();
    });
    ctx.on($('wiz-save'), 'click', async () => {
      const msg = $('wiz-msg');
      msg.textContent = 'Saving…'; msg.style.color = 'var(--sp-muted)';
      const body = {
        action: $('wiz-action').value, scene_id: sceneSel.value, volume: $('wiz-volume').value,
        time: $('wiz-time').value, days: selectedDays(), name: $('wiz-name').value,
      };
      try {
        const res = await api.post('/api/cronwizard', body, { quiet: true });
        msg.style.color = '#28a745';
        msg.textContent = '✓ Scheduled and applied to the crontab: ' + res.description
          + (res.dry_run ? ' (dry run — SP_CRON_APPLY=0, crontab untouched)' : '');
        if (res.command) msg.insertAdjacentHTML('beforeend', `<div><code class="small">${esc(res.command)}</code></div>`);
        ctx.after(1200, reload);
      } catch (e) {
        msg.style.color = '#dc3545';
        msg.textContent = '✗ ' + (e.message || 'Failed to save.');
      }
    });

    // active scenes, by name (the old template's `scenes` context)
    try {
      const scenes = (await api.get('/api/scenes', { quiet: true })).data || [];
      scenes.filter(s => parseInt(s.active, 10) === 1)
        .sort((a, b) => String(a.sceneName || '').localeCompare(String(b.sceneName || '')))
        .forEach(s => { const o = document.createElement('option'); o.value = s.scene_ID; o.textContent = s.sceneName; sceneSel.appendChild(o); });
    } catch (e) { /* the picker stays empty; the server answers "Pick a scene." */ }
    actionChange();   // initialize picker visibility + preview
  },
};

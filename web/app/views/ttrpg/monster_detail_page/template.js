// Monster card markup (templates/ttrpg/monster_detail.html): stat block,
// optional in-combat HP controls for a session instance, and the dice roller
// whose behaviour is the verbatim inline script (script.js).
import { html, raw } from '../../../lib/dom.js';

const AB_PAIRS = [['STR', 'strength'], ['DEX', 'dexterity'], ['CON', 'constitution'], ['INT', 'intelligence'], ['WIS', 'wisdom'], ['CHA', 'charisma']];
const abmod = v => { const m = Math.floor((v - 10) / 2); return (m >= 0 ? '+' : '') + m; };
const kvStr = v => (v && typeof v === 'object' && !Array.isArray(v)) ? Object.entries(v).map(([k, x]) => `${k} ${x}`).join(', ') : String(v);
const section = (title, list) => list && list.length ? html`<div class="mb-3"><h6 style="color:var(--ttrpg-accent);border-bottom:1px solid var(--sp-border);padding-bottom:4px;">${title}</h6><div class="small">${list.map(a => html`<p class="mb-1"><strong>${a.name}.</strong> ${a.desc}</p>`)}</div></div>` : '';

export function render(d) {
  const m = d.m, s = d.stats, sm = d.sm;
  const hpColor = p => p > 50 ? '#28a745' : p > 25 ? '#ffc107' : '#dc3545';
  return html`
<div class="row justify-content-center"><div class="col-lg-8 col-xl-7"><div class="ttrpg-card p-4">
  <div class="d-flex align-items-start gap-3 mb-3 flex-wrap">
    ${d.image_url ? html`<img src="${d.image_url}" alt="" style="width:100px;height:100px;object-fit:contain;border-radius:6px;background:var(--ttrpg-primary);flex-shrink:0;">` : ''}
    <div class="flex-grow-1"><h3 style="color:var(--ttrpg-accent);" class="mb-0">${m.name}</h3>
      <span class="small text-muted d-block mb-2">${[s.size, s.type, s.alignment].filter(Boolean).join(' ')}</span>
      <div class="d-flex gap-2 flex-wrap"><span class="badge" style="background:var(--ttrpg-primary);color:var(--ttrpg-accent);">CR ${m.cr}</span>
        <span class="badge bg-secondary">HP ${m.hp_max}</span><span class="badge bg-secondary">AC ${m.ac}</span>
        ${m.source === 'homebrew' ? html`<span class="badge bg-secondary">Homebrew</span>` : ''}</div></div></div>
  ${sm ? html`<div class="p-3 mb-3" style="border:1px solid var(--ttrpg-accent);border-radius:8px;">
    <div class="d-flex align-items-center gap-2 mb-2"><b style="color:var(--ttrpg-accent);">&#9876; In combat: ${sm.display_name}</b><span id="mc-hp-num" class="small ms-auto">HP ${sm.hp_current} / ${sm.hp_max}</span></div>
    <div class="mb-2" style="background:var(--sp-surface);border-radius:4px;height:10px;overflow:hidden;"><div id="mc-hp-fill" style="height:10px;width:${sm.hp_pct}%;background:${hpColor(sm.hp_pct)};"></div></div>
    <div class="d-flex gap-2 align-items-center flex-wrap"><input id="mc-amt" type="number" value="5" min="1" class="form-control form-control-sm" style="width:80px;text-align:center;">
      <button class="btn btn-sm btn-outline-danger" onclick="mcAdjust(-1)">&#128165; Damage</button><button class="btn btn-sm btn-outline-success" onclick="mcAdjust(1)">&#10010; Heal</button>
      <span id="mc-note" class="small text-muted"></span></div></div>` : ''}
  <div class="p-3 mb-3" style="border:1px solid var(--sp-border);border-radius:8px;">
    <b class="d-block mb-2" style="color:var(--ttrpg-accent);">&#127922; Roll as ${sm ? sm.display_name : m.name}</b>
    <div class="d-flex align-items-center gap-1 mb-2 flex-wrap"><label class="small text-muted mb-0">Dice</label>
      <button class="btn btn-sm btn-outline-secondary px-2 py-0" onclick="mdStepCount(-1)" style="line-height:1.6;">&#8722;</button>
      <input type="number" id="md-count" value="1" min="1" max="20" class="form-control form-control-sm text-center" style="width:52px;">
      <button class="btn btn-sm btn-outline-secondary px-2 py-0" onclick="mdStepCount(1)" style="line-height:1.6;">&#43;</button>
      <label class="small text-muted mb-0 ms-1">Die</label>
      ${[4, 6, 8, 10, 12, 20, 100, 2].map(n => html`<button class="btn btn-sm btn-outline-secondary md-die-btn" data-sides="${n}" onclick="mdSelectDie(${n})" style="min-width:38px;">d${n}</button>`)}</div>
    <div class="d-flex align-items-center gap-2 mb-2"><label class="small text-muted mb-0">Mode</label>
      <div class="btn-group btn-group-sm" role="group"><button id="md-adv-normal" class="btn btn-sm btn-outline-secondary" onclick="mdSetAdvMode('normal')">Normal</button>
        <button id="md-adv-adv" class="btn btn-sm btn-outline-secondary" onclick="mdSetAdvMode('advantage')">Adv</button>
        <button id="md-adv-dis" class="btn btn-sm btn-outline-secondary" onclick="mdSetAdvMode('disadvantage')">Disadv</button></div></div>
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap"><label class="small text-muted mb-0">Mod</label>
      <button type="button" class="btn btn-sm btn-outline-secondary" style="min-width:28px;padding:0 6px;" onclick="var i=document.getElementById('md-mod');i.value=(parseInt(i.value)||0)-1">&#8722;</button>
      <input type="number" id="md-mod" value="0" class="form-control form-control-sm text-center" style="width:58px;">
      <button type="button" class="btn btn-sm btn-outline-secondary" style="min-width:28px;padding:0 6px;" onclick="var i=document.getElementById('md-mod');i.value=(parseInt(i.value)||0)+1">+</button>
      ${s.strength !== undefined && s.strength !== null ? AB_PAIRS.map(([label, key]) => { const v = Math.floor(((s[key] || 10) - 10) / 2); const t = (v >= 0 ? '+' : '') + v; return html`<button class="btn btn-sm btn-outline-secondary stat-mod-btn" onclick="mdSetMod(${v})" title="${label}: ${t}">${label}<br><span style="font-size:.65rem;">${t}</span></button>`; }) : ''}
      <button class="btn btn-sm btn-outline-secondary stat-mod-btn" onclick="mdSetMod(${d.prof})" title="Proficiency (from CR ${m.cr}): +${d.prof}">PROF<br><span style="font-size:.65rem;">+${d.prof}</span></button></div>
    <div class="d-flex gap-2 align-items-center flex-wrap"><input id="md-label" type="text" placeholder="Label (optional)&hellip;" class="form-control form-control-sm" style="max-width:180px;">
      <button class="btn btn-ttrpg btn-sm" onclick="mdRoll()">&#127922; Roll</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="mdReset()" title="Reset to 1d20 +0">&#8635;</button></div>
    <div id="md-quicklabels" class="d-flex gap-1 mt-2 flex-wrap"></div>
    ${d.game && d.game.id === 'dcc' ? html`<div class="small mt-2" style="color:var(--sp-muted);">Dungeon Crawler Carl: the GM doesn't roll to attack &mdash; players roll <b>Evade</b> against this Mob's number. Use this roller for damage and other dice.</div>` : ''}
    <div id="md-system-panel" class="mt-2" style="display:none;"></div>
    <div id="md-result" class="mt-2" style="display:none;font-weight:600;"></div></div>
  ${s.strength !== undefined && s.strength !== null ? html`<div class="row g-1 mb-3 text-center">${AB_PAIRS.map(([label, key]) => { const val = s[key]; return html`<div class="col"><div class="ttrpg-card p-1" style="border-color:var(--sp-border);"><div class="small text-muted">${label}</div>
      <div class="fw-bold" style="color:var(--ttrpg-accent);">${val !== undefined && val !== null ? val : '—'}</div>${val !== undefined && val !== null ? html`<div class="small text-muted">${abmod(val)}</div>` : ''}</div></div>`; })}</div>` : ''}
  <div class="small mb-3">
    ${s.speed ? html`<p class="mb-1"><strong>Speed:</strong> ${kvStr(s.speed)}</p>` : ''}
    ${s.senses && Object.keys(s.senses).length ? html`<p class="mb-1"><strong>Senses:</strong> ${kvStr(s.senses)}</p>` : ''}
    ${s.languages ? html`<p class="mb-1"><strong>Languages:</strong> ${s.languages}</p>` : ''}
    ${s.xp ? html`<p class="mb-1"><strong>XP:</strong> ${s.xp}</p>` : ''}
    ${s.damage_immunities && s.damage_immunities.length ? html`<p class="mb-1"><strong>Damage Immunities:</strong> ${s.damage_immunities.join(', ')}</p>` : ''}
    ${s.damage_resistances && s.damage_resistances.length ? html`<p class="mb-1"><strong>Damage Resistances:</strong> ${s.damage_resistances.join(', ')}</p>` : ''}
    ${s.damage_vulnerabilities && s.damage_vulnerabilities.length ? html`<p class="mb-1"><strong>Damage Vulnerabilities:</strong> ${s.damage_vulnerabilities.join(', ')}</p>` : ''}
    ${s.condition_immunities && s.condition_immunities.length ? html`<p class="mb-1"><strong>Condition Immunities:</strong> ${s.condition_immunities.map(ci => (ci && typeof ci === 'object') ? ci.name : ci).join(', ')}</p>` : ''}</div>
  ${s.special_abilities && s.special_abilities.length ? html`<div class="small mb-3">${s.special_abilities.map(a => html`<p class="mb-1"><strong>${a.name}.</strong> ${a.desc}</p>`)}</div>` : ''}
  ${section('Actions', s.actions)}${section('Legendary Actions', s.legendary_actions)}${section('Reactions', s.reactions)}
  ${s.notes ? html`<div class="mb-3"><h6 style="color:var(--ttrpg-accent);border-bottom:1px solid var(--sp-border);padding-bottom:4px;">Notes &amp; Actions</h6><div class="small" style="white-space:pre-wrap;">${s.notes}</div></div>` : ''}
  <div class="mt-3"><a href="/ttrpg/monsters" class="btn btn-sm btn-outline-secondary">&larr; Monsters &amp; Assets Library</a>
    ${sm ? html`<a href="/ttrpg/sessions/${sm.session_id}" class="btn btn-sm btn-outline-secondary ms-1">Session</a>` : ''}</div>
</div></div></div>${raw('')}`;
}

// ScenePlay theme engine as a module (ported from the old theme.js).
export const SP_THEMES = [
  { id: 'daylight',      name: 'Daylight',  swatch: '#2f6fed' },
  { id: 'ttrpg-classic', name: 'Classic',   swatch: '#c9a84c' },
  { id: 'forest',        name: 'Forest',    swatch: '#6ecf80' },
  { id: 'ocean',         name: 'Ocean',     swatch: '#18c8e8' },
  { id: 'frost',         name: 'Frost',     swatch: '#90d8f8' },
  { id: 'parchment',     name: 'Parchment', swatch: '#e0b860' },
  { id: 'midnight',      name: 'Midnight',  swatch: '#00e5c8', dark: true },
  { id: 'crimson',       name: 'Crimson',   swatch: '#f05050', dark: true },
  { id: 'ember',         name: 'Ember',     swatch: '#ffa020', dark: true },
  { id: 'royal',         name: 'Royal',     swatch: '#b888ff', dark: true },
  { id: 'steel',         name: 'Steel',     swatch: '#9abcd4', dark: true },
];

export function spContrastText(hex) {
  hex = hex.replace(/^#/, '');
  if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
  const r = parseInt(hex.slice(0, 2), 16) / 255, g = parseInt(hex.slice(2, 4), 16) / 255, b = parseInt(hex.slice(4, 6), 16) / 255;
  const lin = c => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const onDark = (L + 0.05) / (0.004 + 0.05), onLight = (1.0 + 0.05) / (L + 0.05);
  return onLight > onDark ? '#ffffff' : '#111118';
}

export function applyOnAccent() {
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--sp-accent').trim();
  if (!accent) return;
  document.documentElement.style.setProperty('--sp-on-accent', spContrastText(accent));
}

function _current() { try { return localStorage.getItem('sp-theme') || 'daylight'; } catch (e) { return 'daylight'; } }

export function setTheme(id) {
  document.documentElement.setAttribute('data-theme', id);
  try { localStorage.setItem('sp-theme', id); } catch (e) {}
  requestAnimationFrame(applyOnAccent);
  _updateSwatchStates(id);
}

function _updateSwatchStates(activeId) {
  document.querySelectorAll('[data-sp-swatch]').forEach(el => {
    const on = el.dataset.spSwatch === activeId;
    el.style.outline = on ? '3px solid var(--sp-accent)' : '2px solid transparent';
    el.style.outlineOffset = on ? '2px' : '0';
    el.style.transform = on ? 'scale(1.22)' : 'scale(1)';
  });
}

export function togglePicker() {
  const p = document.getElementById('sp-theme-panel');
  if (!p) return;
  const open = p.style.display === 'block';
  p.style.display = open ? 'none' : 'block';
  if (!open) _updateSwatchStates(_current());
}

export function initThemePicker() {
  applyOnAccent();
  const container = document.getElementById('sp-swatches');
  if (!container || container.childElementCount) return;
  const addGroupLabel = text => {
    const el = document.createElement('div');
    el.textContent = text;
    el.style.cssText = 'grid-column:1/-1;font-size:.62rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--sp-muted);border-bottom:1px solid var(--sp-border);padding-bottom:3px;margin-bottom:-4px;';
    container.appendChild(el);
  };
  let darkStarted = false;
  addGroupLabel('Light');
  SP_THEMES.forEach(t => {
    if (t.dark && !darkStarted) { darkStarted = true; addGroupLabel('Dark'); }
    const btn = document.createElement('button');
    btn.title = t.name; btn.dataset.spSwatch = t.id; btn.type = 'button';
    btn.style.cssText = ['width:32px', 'height:32px', 'border-radius:50%', 'border:none', 'cursor:pointer', 'padding:0', 'transition:transform .15s, outline .1s', 'background:' + t.swatch, 'display:block'].join(';');
    btn.onclick = () => setTheme(t.id);
    const label = document.createElement('div');
    label.textContent = t.name;
    label.style.cssText = 'font-size:.62rem;margin-top:3px;text-align:center;color:var(--sp-muted);line-height:1.2;';
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;';
    wrap.append(btn, label);
    container.appendChild(wrap);
  });
  _updateSwatchStates(_current());
  const btn = document.getElementById('sp-theme-btn');
  if (btn && !btn._spWired) { btn._spWired = true; btn.addEventListener('click', togglePicker); }
}

let _outsideWired = false;
export function wireOutsideClose() {
  if (_outsideWired) return; _outsideWired = true;
  document.addEventListener('click', e => {
    const p = document.getElementById('sp-theme-panel'), btn = document.getElementById('sp-theme-btn');
    if (!p || p.style.display !== 'block') return;
    if (!p.contains(e.target) && btn && !btn.contains(e.target)) p.style.display = 'none';
  });
}

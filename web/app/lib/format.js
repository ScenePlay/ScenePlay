// Formatting helpers shared with the old site.js.
export function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

export function fmtQueueDur(sec) {
  sec = Number(sec) || 0;
  if (sec >= 3600) return ` (${Math.floor(sec / 3600)}h ${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}m)`;
  if (sec >= 60) return ` (${Math.floor(sec / 60)}m)`;
  return '';
}

export function shortMediaName(name, n = 48) {
  name = name || '';
  return name.length > n ? name.slice(0, n - 1) + '…' : name;
}

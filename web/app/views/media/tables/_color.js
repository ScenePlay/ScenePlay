// Colour helpers for the LED tables. Rows store colours as the text "[r,g,b]"
// (what the WLED / RPiLED senders parse); the grid edits them with
// <input type="color">. Parsing goes through the w3color global
// (web/vendor/w3color.js, loaded by index.html) like the old site.js
// clickColor() did, with a plain hex fallback if it is missing.
const clamp = n => Math.max(0, Math.min(255, parseInt(n, 10) || 0));

export function hexToRgbArr(hex) {
  const w3 = typeof window !== 'undefined' && window.w3color;
  if (w3) {
    const c = w3(String(hex || ''));
    if (c && c.valid) return [c.red, c.green, c.blue];
  }
  return [1, 3, 5].map(i => parseInt(String(hex || '').slice(i, i + 2), 16) || 0);
}

export function rgbArrToHex(v) {
  const a = Array.isArray(v) ? v : [0, 0, 0];
  return '#' + a.slice(0, 3).concat([0, 0, 0]).slice(0, 3).map(n => clamp(n).toString(16).padStart(2, '0')).join('');
}

// "[r,g,b]" (or an array) -> "#rrggbb"
export function rgbTextToHex(txt) {
  if (Array.isArray(txt)) return rgbArrToHex(txt);
  const parts = String(txt || '').replace(/[\[\]\s]/g, '').split(',');
  return rgbArrToHex(parts.length >= 3 ? parts : [0, 0, 0]);
}

// "#rrggbb" -> "[r,g,b]" (the stored form)
export function hexToRgbText(hex) {
  const [r, g, b] = hexToRgbArr(hex);
  return '[' + r + ',' + g + ',' + b + ']';
}

export const rgbCss = v => (Array.isArray(v) && v.length >= 3) ? `rgb(${clamp(v[0])},${clamp(v[1])},${clamp(v[2])})` : 'transparent';

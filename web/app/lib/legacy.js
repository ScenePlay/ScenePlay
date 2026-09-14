// Bridges for verbatim-ported page scripts: expose functions on window for
// onclick="fn()" attributes, and undo it on unmount.
const _stack = [];

export function exposeGlobals(obj) {
  const names = [];
  for (const [k, v] of Object.entries(obj)) { window[k] = v; names.push(k); }
  _stack.push(names);
  return () => unexposeGlobals(names);
}

export function unexposeGlobals(names) {
  for (const k of names) { try { delete window[k]; } catch (e) { window[k] = undefined; } }
}

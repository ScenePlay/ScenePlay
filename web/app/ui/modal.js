export function getModal(el) { return window.bootstrap.Modal.getOrCreateInstance(el); }
export function confirmAsync(text) { return Promise.resolve(window.confirm(text)); }

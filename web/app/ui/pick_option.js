// A small modal with ONE dropdown — the house way to ask the user to pick
// from a list when the grid itself can't host the select. Resolves to the
// chosen option's value, or null on Cancel/close. (Ported verbatim from
// site.js; a typed-number prompt is never acceptable here — see CLAUDE.md.)
export function spPickOption(title, text, label, options, okLabel) {
  return new Promise(resolve => {
    let modal = document.getElementById('spPickModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'spPickModal';
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.innerHTML =
        '<div class="modal-dialog modal-sm"><div class="modal-content">'
        + '<div class="modal-header"><h5 class="modal-title"></h5>'
        + '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>'
        + '<div class="modal-body"><p class="small text-muted sp-pick-text"></p>'
        + '<label class="form-label fw-bold sp-pick-label" for="spPickSelect"></label>'
        + '<select id="spPickSelect" class="form-select"></select></div>'
        + '<div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>'
        + '<button type="button" class="btn btn-primary sp-pick-ok">Add</button></div>'
        + '</div></div>';
      document.body.appendChild(modal);
      modal.addEventListener('hidden.bs.modal', () => { modal._spOpen = false; });
    }
    modal.querySelector('.modal-title').textContent = title;
    modal.querySelector('.sp-pick-text').textContent = text || '';
    modal.querySelector('.sp-pick-label').textContent = label || '';
    const sel = modal.querySelector('#spPickSelect');
    sel.innerHTML = '';
    options.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      sel.appendChild(opt);
    });
    const inst = window.bootstrap.Modal.getOrCreateInstance(modal);
    let done = false;
    const finish = value => { if (!done) { done = true; resolve(value); } };
    const ok = modal.querySelector('.sp-pick-ok');
    ok.textContent = okLabel || 'Add';
    ok.onclick = () => { finish(sel.value); inst.hide(); };
    const start = () => {
      modal._spOpen = true;
      modal.addEventListener('hidden.bs.modal', () => finish(null), { once: true });
      inst.show();
      sel.focus();
    };
    if (modal._spOpen) modal.addEventListener('hidden.bs.modal', start, { once: true });
    else start();
  });
}
window.spPickOption = spPickOption;

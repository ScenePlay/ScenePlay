export async function mount(shell) {
  shell.innerHTML = '<main id="sp-outlet" class="container-fluid mt-3"></main>';
  return shell.querySelector('#sp-outlet');
}
export function unmount() {}

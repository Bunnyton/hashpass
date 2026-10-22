/* Home = search (user 2026-10-23: «при поиске не уезжать никуда»): typing, a kind on the left and
   «все N →» refresh only #results; the address follows (history.replaceState), back/forward work. */
(() => {
  const form = document.querySelector('form[data-live]');
  if (!form) return;
  const box = document.querySelector(form.dataset.live);
  const input = form.querySelector('input[name=q]');
  const kind = form.querySelector('input[name=type]');
  let timer = 0, ticket = 0;
  const load = async (push) => {
    const params = new URLSearchParams();
    if (input.value.trim()) params.set('q', input.value.trim());
    if (kind.value) params.set('type', kind.value);
    const url = '/' + (params.toString() ? '?' + params : '');
    const mine = ++ticket;
    box.setAttribute('aria-busy', 'true');
    try {
      const resp = await fetch(url + (url.includes('?') ? '&' : '?') + 'partial=1', { credentials: 'same-origin' });
      if (mine !== ticket || !resp.ok) return;
      box.innerHTML = await resp.text();
      document.querySelector('.explore-hero')?.classList.toggle('compact', params.toString() !== '');
      history[push ? 'pushState' : 'replaceState'](null, '', url);
      window.hpSort?.(box);
    } finally { if (mine === ticket) box.removeAttribute('aria-busy'); }
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    if (!input.value.trim()) kind.value = '';      // an empty search is the home showcase again
    timer = setTimeout(() => load(false), 180);
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); clearTimeout(timer); load(true); });
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-kind]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    kind.value = a.dataset.kind;
    load(true);
  });
  window.addEventListener('popstate', () => {
    const p = new URLSearchParams(location.search);
    input.value = p.get('q') || '';
    kind.value = p.get('type') || '';
    load(false);
  });
})();

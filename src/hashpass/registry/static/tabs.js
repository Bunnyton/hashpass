/* Tabs: <nav class='tabs'><a href='#panel-id' data-tab>…</a></nav> + <section id='panel-id' class='tab-panel'>.
   The address keeps the open tab (#panel-id), so a link opens it; without JS every panel shows. */
(() => {
  document.querySelectorAll('nav.tabs').forEach((bar) => {
    const links = [...bar.querySelectorAll('a[data-tab]')];
    const panels = links.map((a) => document.getElementById(a.hash.slice(1))).filter(Boolean);
    if (!panels.length) return;
    bar.setAttribute('role', 'tablist');
    const show = (id, focus) => {
      const target = panels.find((p) => p.id === id) ? id : panels[0].id;
      links.forEach((a) => {
        const on = a.hash.slice(1) === target;
        a.setAttribute('role', 'tab');
        a.setAttribute('aria-selected', String(on));
        a.classList.toggle('on', on);
        a.tabIndex = on ? 0 : -1;
        if (on && focus) a.focus();
      });
      panels.forEach((p) => { p.hidden = p.id !== target; p.setAttribute('role', 'tabpanel'); });
    };
    bar.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-tab]');
      if (!a) return;
      e.preventDefault();
      history.replaceState(null, '', a.hash);
      show(a.hash.slice(1));
    });
    bar.addEventListener('keydown', (e) => {          // arrows move between tabs (WAI-ARIA tabs)
      const i = links.findIndex((a) => a.classList.contains('on'));
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (step === undefined) return;
      const next = links[(i + step + links.length) % links.length];
      history.replaceState(null, '', next.hash);
      show(next.hash.slice(1), true);
    });
    const fromHash = () => {
      const id = location.hash.slice(1);
      const inner = id && document.getElementById(id);
      const owner = inner && panels.find((p) => p === inner || p.contains(inner));
      show(owner ? owner.id : panels[0].id);
    };
    window.addEventListener('hashchange', fromHash);
    fromHash();
  });
})();

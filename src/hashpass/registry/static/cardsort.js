/* Sorting for card grids: <select data-sort-for='<grid selector>'> with values name / -at / -tasks /
   owner (a leading «-» = descending); cards carry data-name / data-at / data-tasks / data-owner. */
window.hpSort = (root = document) => {
  root.querySelectorAll('select[data-sort-for]').forEach((sel) => {
    if (sel.dataset.bound) return;
    sel.dataset.bound = '1';
    sel.addEventListener('change', () => {
      const grid = (sel.closest('section') || document).querySelector(sel.dataset.sortFor);
      if (!grid) return;
      const desc = sel.value.startsWith('-');
      const key = sel.value.replace(/^-/, '');
      const val = (el) => el.dataset[key] || '';
      const items = [...grid.children];
      items.sort((a, b) => {
        const x = val(a), y = val(b);
        const nx = Number(x), ny = Number(y);
        const c = (!Number.isNaN(nx) && !Number.isNaN(ny) && x !== '' && y !== '') ? nx - ny : x.localeCompare(y, 'ru');
        return desc ? -c : c;
      });
      items.forEach((el) => grid.appendChild(el));
    });
  });
};
window.hpSort();

/* table.sortable: click a header to sort by that column (again -- the other way).
   A cell sorts by data-sort, else its input/select value, else its text; numbers as numbers. */
(function () {
  function key(td) {
    if (!td) return '';
    if (td.hasAttribute('data-sort')) return td.getAttribute('data-sort');
    var f = td.querySelector('input:not([type=hidden]), select');
    return (f ? f.value : td.textContent).trim();
  }
  function cmp(a, b) {
    var na = parseFloat(a), nb = parseFloat(b);
    if (a !== '' && b !== '' && !isNaN(na) && !isNaN(nb) && String(na) === a && String(nb) === b) return na - nb;
    if (a === '' && b !== '') return 1;          /* empty cells go last either way */
    if (b === '' && a !== '') return -1;
    return a.localeCompare(b, 'ru', {numeric: true, sensitivity: 'base'});
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var head = table.tHead && table.tHead.rows[0];
    var body = table.tBodies[0];
    if (!head || !body) return;
    Array.prototype.forEach.call(head.cells, function (th, i) {
      if (th.hasAttribute('data-nosort')) return;
      th.classList.add('sort');
      th.addEventListener('click', function () {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
        Array.prototype.forEach.call(head.cells, function (h) { h.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
        var rows = Array.prototype.filter.call(body.rows, function (r) { return r.cells.length > 1; });
        rows.sort(function (x, y) {
          var a = key(x.cells[i]), b = key(y.cells[i]);
          if (a === '' || b === '') return cmp(a, b);
          return dir * cmp(a, b);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
})();

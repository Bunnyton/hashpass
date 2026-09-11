/* Catalog editor: drag-and-drop reorder + block-rename autosave + close menus on outside click. */
(function () {
  // -- drag-and-drop across blocks; posts the resulting layout to /web/catalog/layout
  var dragged = null;
  document.addEventListener('dragstart', function (e) {
    var li = e.target.closest && e.target.closest('.titem');
    if (li) { dragged = li; e.dataTransfer.effectAllowed = 'move'; li.classList.add('dragging'); }
  });
  document.addEventListener('dragend', function () {
    if (dragged) dragged.classList.remove('dragging');
    dragged = null;
  });
  document.addEventListener('dragover', function (e) {
    if (!dragged) return;
    var ul = e.target.closest('.tasklist');
    if (!ul) return;
    e.preventDefault();
    var over = e.target.closest('.titem');
    if (over && over !== dragged) {
      var r = over.getBoundingClientRect();
      ul.insertBefore(dragged, (e.clientY - r.top) / r.height > 0.5 ? over.nextSibling : over);
    } else if (!over) {
      ul.appendChild(dragged);
    }
  });
  document.addEventListener('drop', function (e) {
    if (!dragged) return;
    e.preventDefault();
    dragged = null;
    var blocks = [].map.call(document.querySelectorAll('.block'), function (b) {
      return {
        id: b.getAttribute('data-block-id'),
        tasks: [].map.call(b.querySelectorAll('.titem'), function (li) { return li.getAttribute('data-ref'); })
      };
    });
    fetch('/web/catalog/layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks: blocks })
    }).then(function () { location.reload(); });
  });

  // -- inline block-name save when the input loses focus (Enter also blurs it)
  document.addEventListener('change', function (e) {
    var input = e.target.closest && e.target.closest('.block-name-input');
    if (input) input.form.submit();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.classList.contains('block-name-input')) {
      e.preventDefault(); e.target.blur();
    }
  });

  // -- close the three-dot / add menus when clicking elsewhere
  document.addEventListener('click', function (e) {
    document.querySelectorAll('details.menu[open], details.add-menu[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });
})();

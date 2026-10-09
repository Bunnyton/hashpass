/* Catalog editor: pointer drag-and-drop + ↑/↓ moves, block-rename autosave, menus closing. */
(function () {
  var NO_DRAG = 'a, button, summary, details, input, select, textarea, label';
  var EDGE = 70;            // px from the viewport edge where auto-scroll kicks in
  var THRESHOLD = 5;        // px the pointer must travel before a press becomes a drag

  // -- toast (one line at the bottom; replaces the old full-page reload after a move)
  var toastEl = null, toastTimer = null;
  function toast(text, bad) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    toastEl.classList.toggle('bad', !!bad);
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, bad ? 4000 : 1800);
  }

  function snapshot() {
    return [].map.call(document.querySelectorAll('.block'), function (b) {
      return {
        id: b.getAttribute('data-block-id'),
        tasks: [].map.call(b.querySelectorAll('.titem'), function (li) { return li.getAttribute('data-ref'); })
      };
    });
  }

  function renumber() {
    var n = 0;
    document.querySelectorAll('.titem .num').forEach(function (el) { n += 1; el.textContent = '№' + n; });
  }

  function save() {
    renumber();
    fetch('/web/catalog/layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks: snapshot() })
    }).then(function (r) {
      if (r.ok) { toast('Порядок сохранён'); return; }
      toast(r.status === 403 ? 'Порядок заданий меняет только администратор'
                             : 'Не удалось сохранить порядок — обновляю страницу', true);
      setTimeout(function () { location.reload(); }, 1600);
    }).catch(function () {
      toast('Нет связи с пулом — порядок не сохранён', true);
      setTimeout(function () { location.reload(); }, 1600);
    });
  }

  // -- pointer drag: the row floats under the pointer, a placeholder marks the drop spot
  var drag = null;   // {li, ph, startX, startY, dx, dy, active, origin:{list, next}, before}

  document.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    var li = e.target.closest && e.target.closest('.titem');
    if (!li || e.target.closest(NO_DRAG)) return;
    // touch: only the grip starts a drag, so the rest of the row still scrolls the page
    if (e.pointerType === 'touch' && !e.target.closest('.grip')) return;
    var r = li.getBoundingClientRect();
    drag = { li: li, ph: null, startX: e.clientX, startY: e.clientY,
             dx: e.clientX - r.left, dy: e.clientY - r.top, active: false,
             origin: { list: li.parentNode, next: li.nextSibling }, before: JSON.stringify(snapshot()),
             x: e.clientX, y: e.clientY };
  });

  function begin() {
    var li = drag.li, r = li.getBoundingClientRect();
    var ph = document.createElement('li');
    ph.className = 'titem-ph';
    ph.style.height = r.height + 'px';
    li.parentNode.insertBefore(ph, li);
    li.classList.add('floating');
    li.style.width = r.width + 'px';
    document.body.appendChild(li);
    document.body.classList.add('drag-active');
    drag.ph = ph;
    drag.active = true;
    requestAnimationFrame(autoscroll);
  }

  function place() {
    var li = drag.li;
    li.style.left = (drag.x - drag.dx) + 'px';
    li.style.top = (drag.y - drag.dy) + 'px';
    var under = document.elementFromPoint(drag.x, drag.y);   // the floating row has pointer-events:none
    var block = under && under.closest('.block');
    document.querySelectorAll('.block.drop-target').forEach(function (b) {
      if (b !== block) b.classList.remove('drop-target');
    });
    if (!block) return;
    block.classList.add('drop-target');
    var list = block.querySelector('.tasklist');
    var over = under.closest('.titem');
    if (over && over !== drag.ph) {
      var r = over.getBoundingClientRect();
      list.insertBefore(drag.ph, drag.y > r.top + r.height / 2 ? over.nextSibling : over);
      return;
    }
    if (under.closest('.titem-ph')) return;
    // over the block but not over a row: before the first row when above it, else at the end
    var rows = list.querySelectorAll('.titem');
    if (rows.length && drag.y < rows[0].getBoundingClientRect().top) list.insertBefore(drag.ph, rows[0]);
    else list.appendChild(drag.ph);
  }

  function autoscroll() {
    if (!drag || !drag.active) return;
    var v = 0;
    if (drag.y < EDGE) v = -Math.ceil((EDGE - drag.y) / 4);
    else if (drag.y > window.innerHeight - EDGE) v = Math.ceil((drag.y - window.innerHeight + EDGE) / 4);
    if (v) { window.scrollBy(0, v); place(); }
    requestAnimationFrame(autoscroll);
  }

  document.addEventListener('pointermove', function (e) {
    if (!drag) return;
    drag.x = e.clientX; drag.y = e.clientY;
    if (!drag.active) {
      if (Math.abs(e.clientX - drag.startX) + Math.abs(e.clientY - drag.startY) < THRESHOLD) return;
      begin();
    }
    e.preventDefault();
    place();
  });

  function finish(cancel) {
    var d = drag;
    drag = null;
    if (!d || !d.active) return;
    var li = d.li;
    li.classList.remove('floating');
    li.style.left = li.style.top = li.style.width = '';
    document.body.classList.remove('drag-active');
    document.querySelectorAll('.block.drop-target').forEach(function (b) { b.classList.remove('drop-target'); });
    if (cancel) d.origin.list.insertBefore(li, d.origin.next);
    else d.ph.parentNode.insertBefore(li, d.ph);
    d.ph.remove();
    li.classList.add('just-moved');
    setTimeout(function () { li.classList.remove('just-moved'); }, 700);
    if (!cancel && JSON.stringify(snapshot()) !== d.before) save();
  }

  document.addEventListener('pointerup', function () { finish(false); });
  document.addEventListener('pointercancel', function () { finish(true); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && drag) finish(true); });

  // -- ↑ / ↓ from the task's ⋯ menu: one step, crossing into the neighbouring block at the edges
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-move]');
    if (!btn) return;
    e.preventDefault();
    var li = btn.closest('.titem'), list = li.parentNode;
    var lists = [].slice.call(document.querySelectorAll('.tasklist'));
    var i = lists.indexOf(list);
    if (btn.getAttribute('data-move') === 'up') {
      var prev = li.previousElementSibling;
      if (prev) list.insertBefore(li, prev);
      else if (i > 0) lists[i - 1].appendChild(li);
      else return;
    } else {
      var next = li.nextElementSibling;
      if (next) list.insertBefore(next, li);
      else if (i < lists.length - 1) lists[i + 1].insertBefore(li, lists[i + 1].firstChild);
      else return;
    }
    var menu = btn.closest('details');
    if (menu) menu.removeAttribute('open');
    li.classList.add('just-moved');
    setTimeout(function () { li.classList.remove('just-moved'); }, 700);
    save();
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

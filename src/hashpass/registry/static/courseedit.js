/* Course editor extras (user 2026-11-06: «сделай удобнее интерфейс управления порядком и сокрытием
   тасков»): one-click eye toggles for tasks and blocks without a reload, Alt+↑/↓ on a focused grip,
   checkboxes + a bar for bulk hide / show / move, and the scroll position kept across reloads. */
(function () {
  var cat = document.getElementById('cat');
  if (!cat) return;
  // catalog.js (structure editors) brings the toast; a mirror's page has only this file
  var toast = window.hpToast || (function () {
    var el = null, timer = null;
    return function (text, bad) {
      if (!el) {
        el = document.createElement('div');
        el.className = 'toast';
        el.setAttribute('role', 'status');
        el.setAttribute('aria-live', 'polite');
        document.body.appendChild(el);
      }
      el.textContent = text;
      el.classList.toggle('bad', !!bad);
      el.classList.add('show');
      clearTimeout(timer);
      timer = setTimeout(function () { el.classList.remove('show'); }, bad ? 4000 : 1800);
    };
  })();
  // a bulk change can be taken back for a few seconds (ui-ux: undo-support for bulk actions)
  var undoEl = null, undoTimer = null;
  function offerUndo(text, undo, expire) {
    if (!undoEl) {
      undoEl = document.createElement('div');
      undoEl.className = 'toast undo';
      undoEl.setAttribute('role', 'status');
      undoEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(undoEl);
    }
    undoEl.innerHTML = '';
    var span = document.createElement('span');
    span.textContent = text;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'undo-btn';
    btn.textContent = 'Отменить';
    btn.addEventListener('click', function () { hide(); undo(); }, { once: true });
    undoEl.appendChild(span);
    undoEl.appendChild(btn);
    undoEl.classList.add('show');
    function hide() { clearTimeout(undoTimer); undoEl.classList.remove('show'); }
    clearTimeout(undoTimer);
    undoTimer = setTimeout(function () { hide(); if (expire) expire(); }, 7000);
  }
  var KEY = 'hp-scroll:' + location.pathname;

  // -- a reload (menus, chained order) comes back to the same place, not to the top
  try {
    var saved = JSON.parse(sessionStorage.getItem(KEY) || 'null');
    sessionStorage.removeItem(KEY);
    if (saved && Date.now() - saved.at < 15000) window.scrollTo(0, saved.y);
  } catch (e) { /* storage off: just start at the top */ }
  window.addEventListener('beforeunload', function () {
    try { sessionStorage.setItem(KEY, JSON.stringify({ y: window.scrollY, at: Date.now() })); } catch (e) {}
  });
  function reloadIfChained() {
    if (cat.getAttribute('data-chained')) setTimeout(function () { location.reload(); }, 700);
  }

  // -- the eye: aria-pressed=true means hidden from those taking the course
  function put(btn, hide) {
    var field = btn.getAttribute('data-field'), body = {};
    body[field] = field === 'open' ? !hide : hide;
    return fetch(btn.getAttribute('data-toggle-url'), {
      method: 'PUT', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('Ошибка ' + r.status));
        if (j.rev !== undefined) cat.setAttribute('data-rev', j.rev);
        paint(btn, hide);
      });
    });
  }

  function paint(btn, hide) {
    var isBlock = btn.getAttribute('data-field') === 'open';
    var holder = btn.closest(isBlock ? '.block' : '.titem');
    var what = (btn.getAttribute('aria-label') || '').replace(/^(Скрыть|Показать) /, '');
    btn.setAttribute('aria-pressed', hide ? 'true' : 'false');
    btn.setAttribute('aria-label', (hide ? 'Показать ' : 'Скрыть ') + what);
    btn.title = hide ? 'Скрыто — показать проходящим курс' : 'Скрыть от проходящих курс';
    holder.classList.toggle(isBlock ? 'block-hidden' : 'task-hidden', hide);
    if (isBlock) {                                  // its chip in «Порядок открытия»
      var chip = document.querySelector('.flow-chip[href="#blk-' + holder.getAttribute('data-block-id') + '"]');
      if (chip) {
        chip.parentNode.classList.toggle('off', hide);
        if (hide) chip.title = 'скрыт от проходящих курс'; else chip.removeAttribute('title');
      }
    }
    var head = isBlock ? holder.querySelector('.block-head') : holder;
    var pill = head.querySelector(isBlock ? ':scope > .pill.closed' : ':scope > .pill.closed');
    if (hide && !pill) {
      pill = document.createElement('span');
      pill.className = 'pill closed' + (isBlock ? '' : ' sm');
      pill.textContent = isBlock ? 'скрыт' : 'скрыто';
      var after = isBlock ? head.querySelector('.block-rename, b') : holder.querySelector('.tref');
      after.insertAdjacentElement('afterend', pill);
    } else if (!hide && pill) pill.remove();
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.icon-btn.eye');
    if (!btn) return;
    e.preventDefault();
    var hide = btn.getAttribute('aria-pressed') !== 'true';
    btn.disabled = true;
    put(btn, hide).then(function () {
      toast(hide ? 'Скрыто от проходящих курс' : 'Показано проходящим курс');
      reloadIfChained();
    }).catch(function (err) { toast(err.message || 'Нет связи с пулом', true); })
      .then(function () { btn.disabled = false; });
  });

  // -- keyboard: Alt+↑/↓ on a focused grip moves the row, focus stays with it
  document.addEventListener('keydown', function (e) {
    if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    var grip = e.target.closest && e.target.closest('.titem .grip');
    if (!grip) return;
    e.preventDefault();
    var li = grip.closest('.titem');
    var move = li.querySelector('[data-move="' + (e.key === 'ArrowUp' ? 'up' : 'down') + '"]');
    if (move) { move.click(); grip.focus(); }
  });

  // -- selection: checkboxes (Shift — a range) and the bar
  var bar = cat.querySelector('.bulkbar'), last = null;
  function boxes() { return [].slice.call(cat.querySelectorAll('.tsel')); }
  function chosen() { return boxes().filter(function (b) { return b.checked; }); }
  function refresh() {
    var n = chosen().length;
    boxes().forEach(function (b) { b.closest('.titem').classList.toggle('selected', b.checked); });
    if (!bar) return;
    bar.hidden = n === 0;
    bar.querySelector('.bulk-n').textContent = n;
    bar.querySelector('.bulk-word').textContent = n % 10 === 1 && n % 100 !== 11 ? 'задание выбрано'
      : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) ? 'задания выбрано' : 'заданий выбрано';
  }
  cat.addEventListener('click', function (e) {
    var box = e.target.closest && e.target.closest('.tsel');
    if (!box) return;
    if (e.shiftKey && last && last !== box) {
      var all = boxes(), a = all.indexOf(last), b = all.indexOf(box);
      all.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (x) { x.checked = box.checked; });
    }
    last = box;
    refresh();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && chosen().length) { boxes().forEach(function (b) { b.checked = false; }); refresh(); }
  });

  // one after another: each change bumps the course revision; resolves to how many went through
  function apply(eyes, hide) {
    var done = 0;
    return eyes.reduce(function (p, btn) {
      return p.then(function () { return put(btn, hide).then(function () { done += 1; }); });
    }, Promise.resolve()).then(function () { return done; }).catch(function (err) {
      toast((done ? 'Сделано ' + done + ', дальше ошибка: ' : '') + (err.message || 'нет связи с пулом'), true);
      return 0;
    });
  }

  if (bar) {
    bar.addEventListener('click', function (e) {
      var act = e.target.closest && e.target.closest('[data-bulk]');
      if (!act) return;
      var kind = act.getAttribute('data-bulk');
      if (kind === 'clear') { boxes().forEach(function (b) { b.checked = false; }); refresh(); return; }
      var hide = kind === 'hide';
      var eyes = chosen().map(function (b) { return b.closest('.titem').querySelector('.icon-btn.eye'); })
        .filter(function (btn) { return btn && (btn.getAttribute('aria-pressed') === 'true') !== hide; });
      if (!eyes.length) { toast(hide ? 'Выбранные уже скрыты' : 'Выбранные уже видны'); return; }
      act.disabled = true;
      apply(eyes, hide).then(function (done) {
        if (!done) return;
        // chained order: the «после …» pills change -- reload once the undo window is over
        offerUndo((hide ? 'Скрыто: ' : 'Показано: ') + done, function () {
          apply(eyes, !hide).then(function (back) { if (back) { toast('Отменено'); reloadIfChained(); } });
        }, reloadIfChained);
      }).then(function () { act.disabled = false; });
    });
    bar.addEventListener('change', function (e) {
      var sel = e.target.closest && e.target.closest('[data-bulk-move]');
      if (!sel || !sel.value) return;
      var list = cat.querySelector('.tasklist[data-block-id="' + sel.value + '"]');
      var rows = chosen().map(function (b) { return b.closest('.titem'); });
      sel.value = '';
      if (!list || !rows.length || !window.hpSaveLayout) return;
      var back = rows.map(function (li) { return { li: li, list: li.parentNode, next: li.nextElementSibling }; });
      var name = sel.querySelector('option[value="' + list.getAttribute('data-block-id') + '"]');
      rows.forEach(function (li) {
        list.appendChild(li);
        li.classList.add('just-moved');
        setTimeout(function () { li.classList.remove('just-moved'); }, 700);
      });
      window.hpSaveLayout({ noReload: true });
      offerUndo('Перенесено в «' + (name ? name.textContent : 'блок') + '»: ' + rows.length, function () {
        back.slice().reverse().forEach(function (b) {
          b.list.insertBefore(b.li, b.next && b.next.parentNode === b.list ? b.next : null);
        });
        window.hpSaveLayout();
      }, reloadIfChained);
    });
  }
})();

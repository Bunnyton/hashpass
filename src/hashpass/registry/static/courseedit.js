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
  // «Когда откроется…»: one dialog for every block and task (user 2026-11-06: the ⋯ menu was too
  // cramped for the picker). The opener carries the url, what is set now and what to leave out.
  var dlg = document.getElementById('needs-dlg');
  if (dlg && dlg.showModal) {
    var form = dlg.querySelector('form'), opener = null;
    var find = dlg.querySelector('.needs-find'), none = dlg.querySelector('.needs-none');
    var boxes = [].slice.call(dlg.querySelectorAll('input[type=checkbox]'));
    function plural(n, one, few, many) {
      var m10 = n % 10, m100 = n % 100;
      return n + ' ' + (m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many);
    }
    // a box counts when ticked and not the item itself / its own block (a filtered-out one still counts)
    function counts(x) {
      var chip = x.closest('.chip');
      return x.checked && !x.closest('[hidden]') && chip.dataset.skip !== '1';
    }
    function summary() {
      var b = 0, t = 0;
      boxes.forEach(function (x) { if (counts(x)) { if (x.closest('[data-ref]')) t++; else b++; } });
      var parts = [];
      if (b) parts.push(plural(b, 'блок', 'блока', 'блоков'));
      if (t) parts.push(plural(t, 'задание', 'задания', 'заданий'));
      dlg.querySelector('.needs-sum').textContent = parts.length ? 'Ждёт: ' + parts.join(' и ') : 'Откроется сразу';
    }
    function filter() {
      var q = (find.value || '').trim().toLowerCase(), any = false;
      dlg.querySelectorAll('.needs-group').forEach(function (g) {
        if (g.hidden) return;
        var shown = 0;
        g.querySelectorAll('[data-ref]').forEach(function (chip) {
          var skip = chip.dataset.skip === '1';
          var hit = !skip && (!q || chip.textContent.toLowerCase().indexOf(q) >= 0 ||
                              g.querySelector('.needs-gname').textContent.toLowerCase().indexOf(q) >= 0);
          chip.classList.toggle('chip-hidden', !hit);
          if (hit) shown++;
        });
        g.classList.toggle('chip-hidden', !shown);
        if (shown) any = true;
      });
      none.hidden = any;
    }
    function open(btn) {
      opener = btn;
      var have = JSON.parse(btn.getAttribute('data-needs') || '[]');
      var skipBlock = btn.getAttribute('data-skip-block'), skipRef = btn.getAttribute('data-skip-ref');
      dlg.querySelector('#needs-dlg-title').textContent = 'Когда откроется ' + btn.getAttribute('data-needs-title');
      var note = dlg.querySelector('.needs-note'), noteText = btn.getAttribute('data-needs-note');
      note.textContent = noteText || '';
      note.hidden = !noteText;
      dlg.querySelectorAll('.needs-sec > .chips > [data-block]').forEach(function (chip) {
        chip.hidden = chip.getAttribute('data-block') === skipBlock;
      });
      dlg.querySelectorAll('.needs-group').forEach(function (g) {
        var own = g.getAttribute('data-block') === skipBlock;
        g.hidden = own;
        g.dataset.skip = own ? '1' : '';
        g.querySelectorAll('[data-ref]').forEach(function (chip) {
          chip.dataset.skip = chip.getAttribute('data-ref') === skipRef ? '1' : '';
        });
      });
      boxes.forEach(function (x) { x.checked = have.indexOf(x.value) >= 0; });
      find.value = '';
      filter();
      summary();
      dlg.showModal();
      var first = dlg.querySelector('.needs-sec .chip:not([hidden]) input');
      if (first) first.focus();
    }
    function close() {
      dlg.close();
      if (opener && document.contains(opener)) {
        var menu = opener.closest('details.menu');
        if (menu) menu.removeAttribute('open');
        (menu ? menu.querySelector('summary') : opener).focus();
      }
    }
    document.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-needs-url]');
      if (btn) { e.preventDefault(); open(btn); }
    });
    dlg.addEventListener('click', function (e) {
      if (e.target === dlg || (e.target.closest && e.target.closest('[data-dlg-close]'))) close();
      else if (e.target.closest && e.target.closest('[data-needs-clear]')) {
        boxes.forEach(function (x) { x.checked = false; });
        summary();
      }
    });
    dlg.addEventListener('cancel', function (e) { e.preventDefault(); close(); });
    dlg.addEventListener('change', summary);
    find.addEventListener('input', filter);
    find.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!opener) return;
      var needs = boxes.filter(counts).map(function (x) { return x.value; });
      var save = form.querySelector('button[type=submit]');
      save.disabled = true;
      fetch(opener.getAttribute('data-needs-url'), {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ needs: needs })
      }).then(function (r) {
        return r.text().then(function (t) {
          var j = {};
          try { j = t ? JSON.parse(t) : {}; } catch (err) { j = {}; }
          if (!r.ok) throw new Error(j.error || ('Ошибка ' + r.status));
          location.reload();
        });
      }).catch(function (err) {
        save.disabled = false;
        toast(err.message || 'Нет связи с пулом', true);
      });
    });
  }
})();

/* «Пригласить в курс»: a login field with suggestions (GET /users?q=), picked logins become chips,
   the form's hidden `users` carries them to the API (api.js sends the form). User 2026-11-04:
   «пользователи — открытая информация: начинаешь вводить, тебе показывает, что за пользователи». */
(function () {
  [].forEach.call(document.querySelectorAll('form[data-user-search]'), function (form) {
    var input = form.querySelector('input[type=search]');
    var hits = form.querySelector('.user-hits');
    var picked = form.querySelector('.user-picked');
    var hidden = form.querySelector('input[name=users]');
    var chosen = [], timer = null, active = -1;

    function sync() { hidden.value = chosen.join(' '); }
    function pick(login) {
      login = (login || '').trim().replace(/^@/, '');
      if (!login || chosen.indexOf(login) >= 0) return;
      chosen.push(login);
      var chip = document.createElement('span');
      chip.className = 'chip picked';
      chip.textContent = login + ' ';
      var x = document.createElement('button');
      x.type = 'button'; x.className = 'chip-x'; x.textContent = '×';
      x.setAttribute('aria-label', 'убрать ' + login);
      x.addEventListener('click', function () {
        chosen.splice(chosen.indexOf(login), 1); chip.remove(); sync();
      });
      chip.appendChild(x);
      picked.appendChild(chip);
      sync();
      input.value = ''; hide();
    }
    function hide() { hits.hidden = true; hits.innerHTML = ''; active = -1; }
    function show(users) {
      hits.innerHTML = '';
      users.filter(function (u) { return chosen.indexOf(u) < 0; }).forEach(function (u) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.textContent = u;
        li.addEventListener('mousedown', function (e) { e.preventDefault(); pick(u); });
        hits.appendChild(li);
      });
      hits.hidden = !hits.children.length;
      active = -1;
    }
    function mark(i) {
      var items = hits.children;
      if (!items.length) return;
      active = (i + items.length) % items.length;
      [].forEach.call(items, function (li, k) { li.classList.toggle('active', k === active); });
    }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (!q) { hide(); return; }
      timer = setTimeout(function () {
        fetch('/users?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : { users: [] }; })
          .then(function (j) { if (input.value.trim() === q) show(j.users || []); })
          .catch(hide);
      }, 150);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); mark(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); mark(active - 1); }
      else if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
        if (!input.value.trim() && e.key === 'Enter') return;      // empty: submit the form
        e.preventDefault();
        pick(active >= 0 ? hits.children[active].textContent : input.value);
      } else if (e.key === 'Escape') hide();
    });
    input.addEventListener('blur', function () { setTimeout(hide, 150); });
    form.addEventListener('submit', function () { if (input.value.trim()) pick(input.value); }, true);
  });
})();

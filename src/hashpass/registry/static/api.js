/* Course/image pages: a <form data-api="METHOD /path"> sends its fields to the JSON API
   (a path slot __NAME__ is filled from the field `__name`, which is not sent).
   Fields go as JSON (data-type="bool"|"int" converts; a checkbox is a bool, or with
   data-type="list" one of a list of the checked values); data-rev adds the
   page's revision of the course; data-confirm asks first; data-then="go:/c/{ref}" follows the
   answer, else the page reloads. Errors show the server's own `error` text. */
(function () {
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
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, bad ? 5000 : 1800);
  }

  function fields(form) {
    var body = {};
    [].forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled) return;
      var type = el.getAttribute('data-type');
      if (el.type === 'checkbox' && type === 'list') {         // boxes of one name -> a list
        body[el.name] = body[el.name] || [];
        if (el.checked) body[el.name].push(el.value);
      } else if (el.type === 'checkbox') body[el.name] = el.checked;
      else if (type === 'bool') body[el.name] = el.value === 'true' || el.value === 'True';
      else if (type === 'int') body[el.name] = parseInt(el.value, 10);
      else body[el.name] = el.value;
    });
    var rev = form.getAttribute('data-rev');
    if (rev) body.rev = parseInt(rev, 10);
    return body;
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    var spec = form.getAttribute && form.getAttribute('data-api');
    if (!spec) return;
    e.preventDefault();
    var ask = form.getAttribute('data-confirm');
    if (ask && !window.confirm(ask)) return;
    var parts = spec.split(' '), method = parts[0], url = parts.slice(1).join(' ');
    var body = fields(form);
    // a path slot __NAME__ takes the value of the field `__name` (a course picked, a fork's name)
    url = url.replace(/__([A-Z]+)__/g, function (_, key) {
      var k = '__' + key.toLowerCase(), v = body[k];
      delete body[k];
      return encodeURIComponent(v || '').replace(/%2F/g, '/');
    });
    var btn = form.querySelector('button[type=submit], button:not([type])');
    if (btn) btn.disabled = true;
    fetch(url, {
      method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: method === 'GET' ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.text().then(function (t) {
        var j = {};
        try { j = t ? JSON.parse(t) : {}; } catch (err) { j = {}; }
        if (!r.ok) throw new Error(j.error || ('Ошибка ' + r.status));
        if (j.message) toast(j.message);
        var then = form.getAttribute('data-then') || 'reload';
        if (then.indexOf('go:') === 0) {
          location.href = then.slice(3).replace('{ref}', j.ref || '');
        } else {
          setTimeout(function () { location.reload(); }, j.message ? 1200 : 0);
        }
      });
    }).catch(function (err) {
      if (btn) btn.disabled = false;
      toast(err.message || 'Нет связи с пулом', true);
    });
  });

  // a <code class="copy"> copies itself on click
  document.addEventListener('click', function (e) {
    var code = e.target.closest && e.target.closest('code.copy');
    if (!code || !navigator.clipboard) return;
    navigator.clipboard.writeText(code.textContent.trim()).then(function () { toast('Скопировано'); });
  });

  document.addEventListener('click', function (e) {
    document.querySelectorAll('details.menu[open], details.add-menu[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });
})();

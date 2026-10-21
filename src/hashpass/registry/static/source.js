/* Source file page: Просмотр/Код tabs for Markdown, copy the raw file. */
(function () {
  document.querySelectorAll('[data-view]').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('[data-view]').forEach(function (o) {
        var on = o === b;
        o.classList.toggle('on', on); o.classList.toggle('ghost', !on);
        o.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      document.querySelectorAll('[data-pane]').forEach(function (p) {
        p.hidden = p.getAttribute('data-pane') !== b.getAttribute('data-view');
      });
    });
  });
  if (location.hash.match(/^#L\d+$/)) {          /* a line link opens the code, not the preview */
    var code = document.querySelector('[data-view=code]');
    if (code) code.click();
  }
  document.querySelectorAll('.copy-src').forEach(function (b) {
    b.addEventListener('click', function () {
      fetch(b.getAttribute('data-src'), {credentials: 'same-origin'})
        .then(function (r) { return r.text(); })
        .then(function (t) { return navigator.clipboard.writeText(t); })
        .then(function () { b.textContent = 'Скопировано'; setTimeout(function () { b.textContent = 'Копировать'; }, 1500); })
        .catch(function () { b.textContent = 'Не вышло'; });
    });
  });
})();

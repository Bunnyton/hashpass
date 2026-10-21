/* Users page: autosave `group` / `comment` inline edits on blur or Enter.
   The save is a background keepalive POST, not form.submit(): a submit is cancelled by the next
   navigation, so «edit, then click a link» used to lose the edit. */
(function () {
  function save(input) {
    var form = input.form;
    if (input.value === input.defaultValue) return;
    input.classList.remove('saved', 'failed');
    input.classList.add('saving');
    fetch(form.action + '?bg=1', {method: 'POST', body: new URLSearchParams(new FormData(form)),
                                  credentials: 'same-origin', keepalive: true})
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        input.defaultValue = input.value;
        input.classList.add('saved');
      })
      .catch(function () { input.classList.add('failed'); })
      .then(function () { input.classList.remove('saving'); });
  }
  document.addEventListener('change', function (e) {
    var input = e.target.closest && e.target.closest('.inline-edit');
    if (input && input.form && input.form.classList.contains('user-edit')) save(input);
  });
  document.addEventListener('submit', function (e) {   /* no full-page submit for inline edits */
    if (e.target.classList.contains('user-edit')) e.preventDefault();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.classList.contains('inline-edit')) {
      e.preventDefault();
      e.target.blur();
    }
  });
})();

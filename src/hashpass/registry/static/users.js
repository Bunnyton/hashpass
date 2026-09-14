/* Users page: autosave `group` / `comment` inline edits on blur or Enter. */
(function () {
  document.addEventListener('change', function (e) {
    var input = e.target.closest && e.target.closest('.inline-edit');
    if (input && input.form && input.form.classList.contains('user-edit')) input.form.submit();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.classList.contains('inline-edit')) {
      e.preventDefault();
      e.target.blur();
    }
  });
})();

/* The course team: a role picked in a member's form shows that role's rights -- an admin's
   boxes or an author's extras -- and switches the other set off (disabled fields are not sent).
   An extra the viewer may not give stays shown but locked (data-givable="0"). */
(function () {
  function sync(select) {
    var form = select.form;
    [].forEach.call(form.querySelectorAll('fieldset[data-for-role]'), function (set) {
      var off = set.getAttribute('data-for-role') !== select.value;
      set.hidden = off;
      [].forEach.call(set.querySelectorAll('input'), function (el) {
        el.disabled = off || el.getAttribute('data-givable') === '0';
      });
    });
  }
  document.addEventListener('change', function (e) {
    if (e.target.matches && e.target.matches('select[data-rights-role]')) sync(e.target);
  });
  [].forEach.call(document.querySelectorAll('select[data-rights-role]'), sync);
})();

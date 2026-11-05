// Wiki cards that unfold in place (course wiki, search results, home page): «Раскрыть все» /
// «Свернуть все». A document-level handler, so cards the live search swaps in work too.
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-wiki-fold]');
  if (!b) return;
  var open = b.getAttribute('data-wiki-fold') === 'open';
  var scope = b.closest('.search-results, main') || document;
  scope.querySelectorAll('details.wiki-fold').forEach(function (d) { d.open = open; });
});

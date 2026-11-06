// Wiki cards that unfold in place (course wiki, search results, home page): «Раскрыть все» /
// «Свернуть все». A document-level handler, so cards the live search swaps in work too.
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-wiki-fold]');
  if (!b) return;
  var open = b.getAttribute('data-wiki-fold') === 'open';
  var scope = b.closest('.search-results, main') || document;
  scope.querySelectorAll('details.wiki-fold').forEach(function (d) { d.open = open; });
});

// An unfolded card is long, its title far above (user 2026-11-06: «тык в пустое поле сворачивает»):
// a click into the card's empty space folds it -- not on text, a link, code, a button or while
// selecting. The empty space lights up under the mouse; «Свернуть ↑» at the bottom does the same.
(function () {
  var hot = null;
  var LIVE = 'a,button,input,select,textarea,summary,pre,code,img,video,table,label,[tabindex]';
  function overText(x, y) {
    var r = document.caretRangeFromPoint ? document.caretRangeFromPoint(x, y) : null;
    if (!r && document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(x, y);
      if (p) { r = document.createRange(); r.setStart(p.offsetNode, p.offset); }
    }
    if (!r || r.startContainer.nodeType !== 3) return false;
    var node = r.startContainer, at = r.startOffset, len = node.length;
    for (var i = Math.max(0, at - 1); i <= Math.min(len - 1, at); i++) {
      var g = document.createRange();
      g.setStart(node, i);
      g.setEnd(node, i + 1);
      var rects = g.getClientRects();
      for (var k = 0; k < rects.length; k++) {
        var b = rects[k];
        if (x >= b.left - 2 && x <= b.right + 2 && y >= b.top - 4 && y <= b.bottom + 4) return true;
      }
    }
    return false;
  }
  // the open card whose empty space is under (x, y), or null
  function emptyOf(target, x, y) {
    var d = target.closest && target.closest('details.wiki-fold[open]');
    if (!d) return null;
    var live = target.closest(LIVE);                    // only what is inside the card counts (<main> has a tabindex)
    if (live && d.contains(live) && live !== d) return null;
    return overText(x, y) ? null : d;
  }
  function fold(d) {
    d.open = false;
    d.classList.remove('fold-hot');
    if (hot === d) hot = null;
    var top = d.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight) {
      var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      d.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' });
    }
    var s = d.querySelector('summary');
    if (s) s.focus({ preventScroll: true });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-fold-close]');
    if (b) { var c = b.closest('details.wiki-fold'); if (c) fold(c); return; }
    if (e.button !== 0 || String(window.getSelection() || '')) return;   // a selection is reading
    var d = emptyOf(e.target, e.clientX, e.clientY);
    if (d) fold(d);
  });
  var queued = false, last = null;
  document.addEventListener('mousemove', function (e) {
    last = e;
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () {
      queued = false;
      var d = emptyOf(last.target, last.clientX, last.clientY);
      if (d !== hot) {
        if (hot) hot.classList.remove('fold-hot');
        if (d) d.classList.add('fold-hot');
        hot = d;
      }
    });
  });
})();

/* History page: poll the pool every 3 s and swap in new commands/outputs in place.
   Keeps the scroll position and which attempts are folded; new commands flash briefly. */
(function () {
  var box = document.getElementById('history-live');
  if (!box) return;
  var src = box.getAttribute('data-live-src');
  var sig = box.getAttribute('data-sig') || '';
  var state = document.querySelector('.live-state');
  var busy = false;
  function folded() {
    var out = {};
    box.querySelectorAll('details.session[id]').forEach(function (d) { out[d.id] = d.open; });
    return out;
  }
  function count(root) {
    var out = {};
    root.querySelectorAll('.session[id]').forEach(function (s) { out[s.id] = s.querySelectorAll('div.cmd').length; });
    return out;
  }
  function tick() {
    if (busy || document.hidden) return;
    busy = true;
    fetch(src + '&sig=' + encodeURIComponent(sig), {credentials: 'same-origin', cache: 'no-store'})
      .then(function (r) {
        if (r.status === 204) return null;
        if (!r.ok) throw new Error(r.status);
        sig = r.headers.get('X-History-Sig') || sig;
        return r.text();
      })
      .then(function (html) {
        if (state) state.textContent = '';
        if (html === null) return;
        var atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 40;
        var open = folded(), before = count(box);
        box.innerHTML = html;
        box.querySelectorAll('details.session[id]').forEach(function (d) {
          if (d.id in open) d.open = open[d.id];
        });
        box.querySelectorAll('.session[id]').forEach(function (s) {   /* flash what is new */
          var rows = s.querySelectorAll('table.cmds tr');
          var old = before[s.id] || 0;
          for (var i = old + 1; i < rows.length; i++) rows[i].classList.add('fresh');
        });
        if (window.HP && window.HP.localiseTimes) window.HP.localiseTimes(box);
        if (atBottom) window.scrollTo(0, document.body.scrollHeight);
      })
      .catch(function () { if (state) state.textContent = '· нет связи с пулом, повторяю…'; })
      .then(function () { busy = false; });
  }
  setInterval(tick, 3000);
  document.addEventListener('visibilitychange', tick);
})();

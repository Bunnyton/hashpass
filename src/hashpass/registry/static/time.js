/* Every <time class='ts' datetime=UTC> in the viewer's zone: their setting (body data-tz), else the browser's. */
(function () {
  var tz = document.body.getAttribute('data-tz') || undefined;
  var fmt;
  try {
    fmt = new Intl.DateTimeFormat('ru-RU', {timeZone: tz, day: '2-digit', month: '2-digit',
      year: 'numeric', hour: '2-digit', minute: '2-digit'});
  } catch (e) {            /* a zone this browser does not know -> the browser's own */
    tz = undefined;
    fmt = new Intl.DateTimeFormat('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'});
  }
  var zone = tz || Intl.DateTimeFormat().resolvedOptions().timeZone;
  document.querySelectorAll('time.ts').forEach(function (t) {
    var d = new Date(t.getAttribute('datetime'));
    if (isNaN(d)) return;
    t.textContent = fmt.format(d).replace(',', '');
    t.title = zone;
  });
  document.querySelectorAll('.browser-tz').forEach(function (o) {
    o.textContent = 'как в браузере (' + Intl.DateTimeFormat().resolvedOptions().timeZone + ')';
  });
})();

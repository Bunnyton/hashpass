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
  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }
  function ago(d) {
    var s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    var steps = [[60, 'только что'], [3600, 60, 'минуту', 'минуты', 'минут'], [86400, 3600, 'час', 'часа', 'часов'],
                 [86400 * 30, 86400, 'день', 'дня', 'дней'], [86400 * 365, 86400 * 30, 'месяц', 'месяца', 'месяцев'],
                 [Infinity, 86400 * 365, 'год', 'года', 'лет']];
    if (s < steps[0][0]) return steps[0][1];
    for (var i = 1; i < steps.length; i++) {
      if (s < steps[i][0]) {
        var n = Math.floor(s / steps[i][1]);
        return n + ' ' + plural(n, steps[i][2], steps[i][3], steps[i][4]) + ' назад';
      }
    }
    return '';
  }
  function localiseTimes(root) {
    root.querySelectorAll('time.ts').forEach(function (t) {
      var d = new Date(t.getAttribute('datetime'));
      if (isNaN(d)) return;
      var full = fmt.format(d).replace(',', '');
      if (t.hasAttribute('data-rel')) {        /* «2 дня назад», GitHub-style; the date in the tooltip */
        t.textContent = ago(d);
        t.title = full + ' (' + zone + ')';
        return;
      }
      t.textContent = full;
      t.title = zone;
    });
  }
  window.HP = window.HP || {};
  window.HP.localiseTimes = localiseTimes;   /* pages that swap HTML in (history.js) call it again */
  localiseTimes(document);
  document.querySelectorAll('.browser-tz').forEach(function (o) {
    o.textContent = 'как в браузере (' + Intl.DateTimeFormat().resolvedOptions().timeZone + ')';
  });
})();

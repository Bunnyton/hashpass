---
tags: git, bisect, отладка, поиск
---
# Поиск виновника делением пополам: git bisect

Тест упал. Год назад всё работало, с тех пор — сотни коммитов. Читать их подряд — день
работы. Но есть приём из игры «угадай число», и git умеет его делать сам: `git bisect`.

## Приём «угадай число»

1. Возьми коммит посередине между «точно хорошо» и «точно плохо».
2. Проверь его. Хорошо — поломка в более новой половине, плохо — в более старой.
3. Возьми эту половину и снова спроси про её середину.

Каждый вопрос отбрасывает половину. 40 коммитов — 5–6 проверок, 300 — 8–9, тысяча — 10.
Это логарифм по основанию 2: удвоил историю — добавилась одна проверка.

## Что считать «плохо»

Нужна проверка, которая на каждом коммите честно отвечает «да/нет». Лучше всего — скрипт:
молчит и выходит с кодом 0, когда всё хорошо, и ругается с кодом не 0, когда плохо. В
примере ниже — перевод температуры в фаренгейты и его проверка `check.sh`:

    $ ./check.sh
    f.sh 100: ждали 212, получили 230
    $ echo $?
    1

## bisect вручную

Начинаешь поиск и называешь две точки: где плохо и где было хорошо (коммит или тег):

    $ git bisect start
    status: waiting for both good and bad commits
    $ git bisect bad
    status: waiting for good commit(s), bad commit known
    $ git bisect good v1.0
    Bisecting: 19 revisions left to test after this (roughly 4 steps)
    [631a0bb739f8e4352445758d3db9223499b734ef] README: правка 20

`git bisect bad` без хеша — «плохо здесь, в текущем коммите». Git сразу переставил каталог
на середину. Проверяешь и отвечаешь:

    $ ./check.sh
    $ git bisect good
    Bisecting: 9 revisions left to test after this (roughly 3 steps)
    [f61bfd68e61e0c212fb3f556e5716c2b363119b8] README: правка 30
    $ ./check.sh
    f.sh 100: ждали 212, получили 230
    $ git bisect bad
    Bisecting: 4 revisions left to test after this (roughly 2 steps)
    [51147a54d988f97a927b6d8ba69655b1e3edc8d9] README: правка 25

И так, пока не останется один коммит — тогда git напишет `… is the first bad commit` и
покажет его.

Пока идёт поиск, ты **не на ветке**, а на коммите посреди истории («HEAD detached»). Не
коммить здесь ничего. Не можешь проверить коммит (например, он не собирается) —
`git bisect skip`, git возьмёт соседний.

## Ход поиска и выход

    $ git bisect log
    git bisect start
    # status: waiting for both good and bad commits
    # bad: [9039565d386ef0c3d60adfc48465066ce2eedd81] README: правка 40
    git bisect bad 9039565d386ef0c3d60adfc48465066ce2eedd81
    # status: waiting for good commit(s), bad commit known
    # good: [27b0aa7e1bc56032d19ff95668be74e0383373ed] Перевод в фаренгейты
    git bisect good 27b0aa7e1bc56032d19ff95668be74e0383373ed
    # good: [631a0bb739f8e4352445758d3db9223499b734ef] README: правка 20
    git bisect good 631a0bb739f8e4352445758d3db9223499b734ef
    # bad: [f61bfd68e61e0c212fb3f556e5716c2b363119b8] README: правка 30
    git bisect bad f61bfd68e61e0c212fb3f556e5716c2b363119b8

Журнал удобно приложить к разбору ошибки, а `git bisect replay файл` повторит поиск.
Закончить поиск и вернуться туда, где был, — `git bisect reset`:

    $ git bisect reset
    Previous HEAD position was 51147a5 README: правка 25
    Switched to branch 'main'

Забудешь — так и останешься посреди истории, а git будет напоминать «currently bisecting».

## А можно без ручных ответов?

Можно: если проверка — скрипт с честным кодом выхода (0 — хорошо, иначе — плохо), git умеет
сам запускать его на каждом шаге и сам отвечать good/bad. Как — в `git bisect --help`, раздел
про автоматический поиск. Сначала пройди поиск руками: тогда понятно, что делает автоматика и
почему ей нужен честный код выхода.

## Нашёл — что дальше

Виновник найден, а после него — ещё куча хороших коммитов. Их терять нельзя, поэтому ветку
**не откатывают** назад (`git reset` выбросил бы всё после), а отменяют один коммит новым
коммитом-противоположностью — как в [задании про git log](/web/wiki/bunnyton/git-log):

    $ git revert --no-edit a7dd441
    [main 2a6b0fb] Revert "f.sh: формула попроще"
     1 file changed, 1 insertion(+), 1 deletion(-)
    $ ./check.sh && echo ok
    ok

Отмена ляжет поверх всего остального, история не переписана — такую правку спокойно
отправляют на общий сервер.

## Где пригодится

- «Раньше работало, теперь нет» — в любом проекте с историей: скорость, вывод, сборка.
- Проверкой может быть что угодно с кодом выхода: `make test`, `grep -q`, `curl -f`.
- Можно искать и не поломку, а момент перемены: `git bisect start --term-old=было --term-new=стало`.

## Источники

- [git-bisect](https://git-scm.com/docs/git-bisect) — официальная справка: skip, run, коды
  выхода, свои термины.
- [Pro Git: Обнаружение ошибок с помощью Git](https://git-scm.com/book/ru/v2/Инструменты-Git-Обнаружение-ошибок-с-помощью-Git) —
  blame и bisect, на русском.
- [git-revert](https://git-scm.com/docs/git-revert) — отмена коммита новым коммитом.

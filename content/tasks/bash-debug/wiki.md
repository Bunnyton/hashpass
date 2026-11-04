---
tags: bash, отладка, shellcheck, set -euo pipefail, скрипты
---
# Отладка bash-скриптов и классические ловушки

bash прощает многое: несуществующая переменная становится пустой строкой, упавшая команда не
останавливает скрипт, конвейер «успешен», если успешно последнее звено. Скрипт молча делает не
то — и узнаёшь об этом по последствиям. Здесь — как искать такие ошибки и самые частые из них.

## Инструменты

1. **Сообщение bash.** Файл, номер строки, что не понравилось. Читай целиком.
2. **`bash -x скрипт`** — трассировка: каждая команда перед запуском, с подставленными
   значениями:

   ```
   $ bash -x t.sh
   + f=report
   + echo report.txt
   report.txt
   + cp report.txt /tmp/
   cp: cannot stat 'report.txt': No such file or directory
   ```

   Для куска скрипта — `set -x` … `set +x` внутри него.
3. **`shellcheck скрипт`** — статический анализатор: читает скрипт, не запуская. У каждого
   замечания код и страница с объяснением. Так он нашёл ошибку в `count-errors.sh` задания:

   ```
   In count-errors.sh line 7:
               count=$((count + 1))
               ^---^ SC2030 (info): Modification of count is local (to subshell caused by pipeline).
   In count-errors.sh line 11:
   echo "Ошибок: $count"
                 ^----^ SC2031 (info): count was modified in a subshell. That change might be lost.
   ```

   Есть [онлайн](https://www.shellcheck.net/) и плагины для редакторов (vim, VS Code).

## Ловушка 1: концы строк Windows

Файл из Windows заканчивает строки `\r\n`. bash считает `\r` частью слова:

```
$ ./win.sh
bash: ./win.sh: cannot execute: required file not found
$ cat -A win.sh
#!/bin/bash^M$
echo hi^M$
$ file win.sh
win.sh: Bourne-Again shell script, ASCII text executable, with CRLF line terminators
```

Программы `/bin/bash\r` нет. Лечение: `sed -i 's/\r$//' файл` или `dos2unix файл`. Чтобы не
повторялось — в git `.gitattributes` с `*.sh text eol=lf`.

## Ловушка 2: переменная в конвейере

Каждое звено конвейера — отдельный процесс со своей копией переменных:

```
$ n=0; printf "a\nb\n" | while read -r l; do n=$((n + 1)); done; echo $n
0
```

Цикл посчитал до 2 — в своей копии. Решение — подать вход перенаправлением: `done < файл` или
`done < <(команда)` (подстановка процесса).

## Ловушка 3: return возвращает код, а не значение

```
$ f() { return 300; }; f; echo $?
44
```

Код — число 0–255 (300 по модулю 256 = 44), строку `return` не примет вовсе: «numeric argument
required». Значение функция печатает, вызывающий забирает `$( )`:

```
$ upper() { echo "${1^^}"; }; name=$(upper anya); echo $name
ANYA
```

Переменные внутри функции — `local`, иначе они перезапишут одноимённые снаружи.

## Ловушка 4: несуществующая переменная

```
$ bash -c 'echo "[$NOPE]"; echo дальше'
[]
дальше
```

Опечатка в имени — и путь `"$CACHE_DIR"/*` становится `/*`. Так в 2015 году скрипт Steam для
Linux с `rm -rf "$STEAMROOT/"*` стирал пользователям домашние каталоги.

## Строгий режим: set -euo pipefail

```
$ bash -c 'set -u; echo "[$NOPE]"'
bash: line 1: NOPE: unbound variable
$ bash -c 'set -e; ls /nope; echo не дойдём'
ls: cannot access '/nope': No such file or directory
$ bash -c 'false | true; echo $?; set -o pipefail; false | true; echo $?'
0
1
$ bash -c 'D=; echo "${D:?пустая переменная}"'
bash: line 1: D: пустая переменная
```

| Опция | Что делает |
|---|---|
| `set -u` | несуществующая переменная — ошибка |
| `set -e` | первая упавшая команда останавливает скрипт |
| `set -o pipefail` | конвейер падает, если упало любое звено |
| `${VAR:?текст}` | пустая или не задана — остановиться с сообщением |

`set -e` не всесилен: он не срабатывает внутри `if`, `&&`/`||` и в некоторых других местах —
подробности в BashFAQ/105. Но вместе с `-u` и `pipefail` он ловит большинство молчаливых бед.
Начало почти любого серьёзного скрипта:

    #!/bin/bash
    set -euo pipefail

## Где это пригодится

- Скрипт из чужого репозитория или чата «не работает» — `file`, `cat -A`, `bash -x`.
- Перед тем как поставить скрипт в cron или службу — `shellcheck`: там его ошибки уже никто не
  увидит глазами.
- Любой скрипт, который удаляет, — `set -u` и `${VAR:?}`.

## Источники

- [ShellCheck](https://www.shellcheck.net/) и [исходники на GitHub](https://github.com/koalaman/shellcheck)
  — список проверок с объяснениями.
- [BashPitfalls](https://mywiki.wooledge.org/BashPitfalls) — каталог типичных ошибок bash.
- [BashFAQ/024: почему переменная теряется после цикла с конвейером](https://mywiki.wooledge.org/BashFAQ/024).
- [BashFAQ/105: почему set -e не делает того, что ждёшь](https://mywiki.wooledge.org/BashFAQ/105).
- [История со Steam: issue #3671](https://github.com/ValveSoftware/steam-for-linux/issues/3671).
- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), встроенная
  команда `set`.
- [bash-handbook](https://github.com/denysdovhan/bash-handbook) (раздел «Отладка»),
  [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md),
  [awesome-bash](https://github.com/awesome-lists/awesome-bash) — там же линтеры и форматтеры.

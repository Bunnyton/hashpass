---
tags: основы, файлы, текст, apt, sudo
---
# Полевой устав: файлы, подсчёт строк, пакеты

Короткий маршрут по самому нужному в консоли: записать слово в файл, посчитать строки в
журнале, поставить программу из репозитория и запустить её. У каждого шага — своя маленькая
ловушка, о них тоже здесь.

## Записать в файл

`echo` печатает текст, а `>` отправляет печать не на экран, а в файл:

    $ echo Привет > note.txt
    $ cat note.txt
    Привет

`>` создаёт файл или **перезаписывает** его целиком. `>>` дописывает в конец:

    $ echo мир >> note.txt
    $ cat note.txt
    Привет
    мир

Проверяй результат `cat`-ом — всегда. Подробнее про `>` и `>>` — в
[wiki про потоки](/web/wiki/bunnyton/streams).

## Регистр букв важен

Для Linux `готово`, `Готово` и `ГОТОВО` — три разных слова. Это касается всего: имён файлов
(`Notes.txt` и `notes.txt` спокойно живут рядом), команд (`LS` не найдётся) и поиска.
Если нужно ровно слово — пиши его буква в букву. Пробелы и лишние символы тоже считаются:
`ок` и `ок ` (с пробелом) — разные строки.

## Найти и посчитать строки

Журнал программы — обычный текстовый файл. Пример:

    $ cat app.log
    2026-11-01 10:00 INFO start
    2026-11-01 10:01 WARN disk 85%
    2026-11-01 10:02 INFO ok
    2026-11-01 10:03 warn disk 90%
    2026-11-01 10:04 WARN disk 95%

`grep` показывает строки, где нашлось слово. Посчитать их можно тремя путями — выбирай
любой:

    $ grep WARN app.log
    2026-11-01 10:01 WARN disk 85%
    2026-11-01 10:04 WARN disk 95%
    $ grep -c WARN app.log
    2
    $ grep WARN app.log | wc -l
    2
    $ awk '/WARN/{n++} END{print n}' app.log
    2

- `grep -c` — сразу число строк с находкой;
- `| wc -l` — конвейер: `wc -l` считает строки во всём, что ему пришло;
- `awk` — маленький язык: «на каждой строке с WARN прибавь 1, в конце напечатай».

И снова регистр: `warn` строчными grep не считает. Ключ `-i` уравнивает буквы:

    $ grep -ci warn app.log
    3

Где именно находки — `grep -n` допишет номера строк:

    $ grep -n WARN app.log
    2:2026-11-01 10:01 WARN disk 85%
    5:2026-11-01 10:04 WARN disk 95%

`grep -c` считает **строки**, а не слова: два WARN в одной строке — это 1. Больше приёмов —
в [wiki про grep](/web/wiki/bunnyton/grep-hunt) и [регулярки](/web/wiki/bunnyton/regex).

## Поставить программу: sudo и apt

Программы в Debian приходят **пакетами** из репозитория, ставит их `apt`. Установка меняет
систему, поэтому обычному пользователю apt откажет:

    $ apt-get install -y cowsay
    E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)
    E: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), are you root?

Права root на одну команду одалживает `sudo` перед ней ([про sudo](/web/wiki/bunnyton/sudo-basics)).
Вторая ловушка — **список пакетов**. apt ищет пакеты в своём списке, скачанном когда-то; в
свежей системе он может быть пустым или старым — тогда `Unable to locate package`. Список
обновляет `apt update`, и только потом `apt install`. Есть ли пакет и какая версия встанет,
покажет `apt-cache policy` (это можно без sudo):

    $ apt-cache policy cowsay
    cowsay:
      Installed: (none)
      Candidate: 3.03+dfsg2-8
      Version table:
         3.03+dfsg2-8 500
            500 http://deb.debian.org/debian trixie/main amd64 Packages

`Installed: (none)` — пока не стоит. Подробнее про apt — в [wiki про apt update](/web/wiki/bunnyton/apt-update).

## Куда пакет положил файлы

`dpkg -L пакет` перечисляет всё, что пакет разложил по системе:

    $ dpkg -L hostname | head -4
    /.
    /usr
    /usr/bin
    /usr/bin/hostname

Программы ищутся по каталогам из переменной `PATH`. Игры и забавы в Debian живут в
`/usr/games` — он в `PATH` обычного пользователя есть, поэтому их запускают просто по имени.
Не находится — `dpkg -L` скажет, где файл, и его можно запустить полным путём.

## Не ленись читать вывод

Почти каждая ошибка выше сама говорит, что не так: `Permission denied` — не хватает прав,
`Unable to locate package` — не знаю такого пакета, `No such file or directory` — нет файла
по этому пути. Прочитать последнюю строку ответа — половина решения.

## Источники

- [man 1 grep](https://man7.org/linux/man-pages/man1/grep.1.html) и
  [man 1 wc](https://man7.org/linux/man-pages/man1/wc.1.html) — поиск и подсчёт.
- [Debian Handbook: APT](https://www.debian.org/doc/manuals/debian-handbook/apt.ru.html) —
  глава на русском: репозитории, update, install.
- [Apt — Debian Wiki](https://wiki.debian.org/ru/Apt) — коротко о командах apt.
- [man 8 sudo](https://man7.org/linux/man-pages/man8/sudo.8.html) — как работает sudo.
- [Пакет sl в Debian](https://packages.debian.org/trixie/sl) — паровоз, который едет по экрану,
  если ошибиться в `ls`.

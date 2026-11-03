---
tags: xargs, awk, cut, текст, архивы
---
# Столбцы и строки: cut, awk, xargs

В Linux почти всё — текст: конфиги, списки пользователей, вывод `ls -l`. И почти всегда этот
текст — таблица: строки, а в строке столбцы. Отсюда два навыка: **вырезать нужный столбец** и
**сделать что-то с каждой строкой**.

## cut — столбцы по разделителю

`cut` режет строку по одному символу-разделителю (`-d`) и берёт нужные поля (`-f`):

    $ cat users.txt
    anna:x:1001:Анна Петрова
    boris:x:1002:Борис Ким
    $ cut -d: -f1 users.txt
    anna
    boris
    $ cut -d: -f1,4 users.txt
    anna:Анна Петрова
    boris:Борис Ким

Без `-d` разделитель — табуляция. Так устроены `/etc/passwd`, `/etc/group`, CSV-выгрузки.

## awk — столбцы по пробелам

В выводе команд и во многих конфигах столбцы разделены **пробелами разной длины** — их
выравнивают для глаз. `cut` такое не любит: для него каждый пробел — отдельный разделитель:

    $ echo 'a   b    c' | cut -d' ' -f2

    $ echo 'a   b    c' | awk '{print $2}'
    b

`awk` считает любую пачку пробелов и табуляций одним разделителем. `$1`, `$2`… — столбцы,
`$0` — вся строка, `$NF` — последний столбец:

    $ awk '{print $3}' shop.log | head -3
    INFO
    WARN
    ERROR

Другой разделитель — `-F`: `awk -F: '{print $4}' users.txt` работает как `cut -d: -f4`.

Строки-комментарии (с `#` в начале) в таблицу не входят — их отсекают раньше, например
`grep -v '^#'` (про `^` — в [wiki regex](/web/wiki/bunnyton/regex)).

## xargs — строки в аргументы

Многие команды не читают stdin: `rm`, `cp`, `mkdir`, `unzip` ждут имена **в аргументах**.
`xargs` превращает поток строк в аргументы команды. Посмотреть, что он соберёт, удобно через
`echo`:

    $ ls pics | grep jpg | xargs echo rm
    rm a.jpg b.jpg c.jpg

Без ключей `xargs` подставляет **все строки разом** в одну команду. Хорошо для `rm`, плохо для
команд, которые берут ровно один аргумент.

## `-I {}` — по команде на каждую строку

    $ ls pics | grep jpg | xargs -I {} echo cp pics/{} backup/
    cp pics/a.jpg backup/
    cp pics/b.jpg backup/
    cp pics/c.jpg backup/

`-I {}` — «запусти команду для каждой строки, подставив её вместо `{}`». Метка может быть
любой: `-I %` работает так же. А `-n 1` — «по одному аргументу на запуск», в конец команды:

    $ echo один два три | xargs -n 1 echo слово:
    слово: один
    слово: два
    слово: три

Ключ `-t` печатает каждую команду перед запуском — помогает понять, что происходит.

## Архивы: один архив — одна команда

`unzip` распаковывает один архив, а остальные имена считает файлами **внутри** него:

    $ unzip zips/p1.zip zips/p2.zip
    Archive:  zips/p1.zip
    caution: filename not matched:  zips/p2.zip

`.zip` распаковывает `unzip`, `.tar.gz` — `tar -xzf`. Куда: `unzip -d каталог`,
`tar -xzf архив -C каталог`, иначе — в текущий каталог. `unzip -o` перезаписывает без вопросов.

Расширение — просто часть имени, оно может врать. Что внутри на самом деле, скажет `file`:

    $ file zips/p1.zip zips/strange.bin
    zips/p1.zip:      Zip archive data, made by v3.0 UNIX, extract using at least v1.0, last modified Nov 04 2026 02:18:04, uncompressed size 7, method=store
    zips/strange.bin: gzip compressed data, from Unix, original size modulo 2^32 10240

`gzip compressed data` — чаще всего `.tar.gz`. Заглянуть, не распаковывая, — `tar -tzf`.

## Грабли

- Пробелы в именах: `xargs` режет по пробелам, и `my photo.jpg` станет двумя файлами:

      $ find pics -name '*.jpg' | xargs ls
      ls: cannot access 'pics/my': No such file or directory
      ls: cannot access 'photo.jpg': No such file or directory
      pics/a.jpg
      pics/b.jpg
      pics/c.jpg
      $ find pics -name '*.jpg' -print0 | xargs -0 ls
      pics/a.jpg
      pics/b.jpg
      pics/c.jpg
      pics/my photo.jpg

  `-print0` и `-0` разделяют имена нулевым байтом, который в имени встретиться не может.
  С `-I {}` строка берётся целиком, пробелы внутри не мешают.
- Прежде чем запускать опасное (`rm`), поставь `echo` перед командой и посмотри, что выйдет.

## Источники

- `man xargs` — [на man7.org](https://man7.org/linux/man-pages/man1/xargs.1.html).
- `man cut` — [на man7.org](https://man7.org/linux/man-pages/man1/cut.1.html).
- [AWK — Википедия](https://ru.wikipedia.org/wiki/AWK) — язык целиком, не только `print $2`.
- [xargs — Википедия](https://ru.wikipedia.org/wiki/Xargs).
- `man tar` — [на man7.org](https://man7.org/linux/man-pages/man1/tar.1.html); `man file` —
  [на man7.org](https://man7.org/linux/man-pages/man1/file.1.html).

---
tags: основы, ls, cat, man, справка
---
# Первые команды: ls, cat, ключи, --help и man

Шесть вещей, с которых начинается любая работа в консоли: осмотреться, прочитать файл, увидеть
подробности и скрытое, спросить команду о ней самой и открыть её руководство.

## ls — что здесь лежит

    $ ls
    recipes
    shopping.txt

`ls` (list) показывает содержимое **текущего** каталога. Можно и чужого: `ls /etc`,
`ls recipes`. В настоящем терминале имена идут в строку, а каталоги подсвечены цветом.

## cat — прочитать файл

    $ cat shopping.txt
    молоко
    хлеб

`cat` печатает файл целиком. Файлов можно дать несколько — выведет подряд:

    $ cat shopping.txt recipes/soup.py
    молоко
    хлеб
    print("hi")

Ошибки у него говорящие:

    $ cat nosuch.txt
    cat: nosuch.txt: No such file or directory
    $ cat recipes
    cat: recipes: Is a directory

Длинный файл удобнее листать через `less имя` (выход — `q`). Если команда «зависла» — `Ctrl+C`.

## Ключи

Почти у каждой команды есть **ключи** — они меняют её поведение. Пишутся после команды через
пробел, с дефисом. `-l` (long) показывает подробности:

    $ ls -l
    total 4
    drwxrwxr-x 2 anya anya 60 Nov  3 18:30 recipes
    -rw-rw-r-- 1 anya anya 22 Oct  1 09:00 shopping.txt

Слева направо: тип и права (`d` — каталог, `-` — файл), число имён, владелец, группа, размер
в байтах, время изменения, имя. `-t` сортирует по времени, `-r` переворачивает порядок, а
ключи склеиваются как угодно — `-l -t -r`, `-ltr`, `-rtl` одно и то же:

    $ ls -ltr
    total 4
    -rw-rw-r-- 1 anya anya 22 Oct  1 09:00 shopping.txt
    drwxrwxr-x 2 anya anya 60 Nov  3 18:30 recipes

## Скрытые файлы

Файл, чьё имя начинается с точки, — **скрытый**: обычный `ls` его не показывает. Так прячут
настройки (`.bashrc`, `.ssh`), чтобы не мешали. Показать всё — ключ `-a` (all):

    $ ls -la
    total 8
    drwxrwxr-x 3 anya anya 100 Nov  4 02:14 .
    drwx------ 4 anya anya 180 Nov  4 02:14 ..
    -rw-rw-r-- 1 anya anya  11 Sep 15 12:00 .config_rc
    drwxrwxr-x 2 anya anya  60 Nov  3 18:30 recipes
    -rw-rw-r-- 1 anya anya  22 Oct  1 09:00 shopping.txt

`.` — сам этот каталог, `..` — тот, что выше. `-A` покажет скрытое без этих двух, `-h` —
размеры в К/М/Г.

## --help — короткая справка

Бывают ключи-слова, перед ними два дефиса. `--help` есть почти у каждой команды:

    $ ls --help
    Usage: ls [OPTION]... [FILE]...
    List information about the FILEs (the current directory by default).
    Sort entries alphabetically if none of -cftuvSUX nor --sort is specified.

    Mandatory arguments to long options are mandatory for short options too.
      -a, --all                  do not ignore entries starting with .
      -A, --almost-all           do not list implied . and ..
    …

Квадратные скобки в `Usage` — «можно не писать», `...` — «можно несколько».

## man — полное руководство

`man команда` открывает руководство (manual). Внутри:

| Клавиша | Что делает |
|---|---|
| стрелки, `Пробел`, `b` | листать |
| `/слово`, Enter | искать слово; `n` — следующее, `N` — предыдущее |
| `g`, `G` | в начало, в конец |
| `q` | выйти |

Руководства разбиты на **разделы**: 1 — команды, 5 — форматы файлов, 7 — обзоры, 8 — команды
администратора. Одно имя бывает в нескольких:

    $ whatis passwd
    passwd (1)           - change user password
    passwd (1ssl)        - OpenSSL application commands
    passwd (5)           - the password file

`man 5 passwd` откроет нужный раздел. Не помнишь имя команды — ищи по описанию:

    $ apropos -s1 copy
    atophide (1)         - partly copy raw log file and/or anonymize raw log
    bup-get (1)          - copy repository items (CAUTION: EXPERIMENTAL)
    cp (1)               - copy files and directories
    cpio (1)             - copy files to and from archives
    dd (1)               - convert and copy a file
    …

## Порядок, когда не знаешь

1. `команда --help` — быстро вспомнить ключ.
2. `man команда` и `/слово` — разобраться всерьёз.
3. Поисковик — когда не знаешь даже, какая команда нужна.

## Источники

- [`man 1 ls`](https://man7.org/linux/man-pages/man1/ls.1.html) и
  [`man 1 cat`](https://man7.org/linux/man-pages/man1/cat.1.html) — все ключи.
- [`man 1 man`](https://man7.org/linux/man-pages/man1/man.1.html) — разделы и поиск.
- [Команда ls в Linux — Losst](https://losst.pro/komanda-ls-linux) — ключи ls по-русски.
- [explainshell.com](https://explainshell.com/) — вставь команду, и сайт объяснит каждый её ключ.

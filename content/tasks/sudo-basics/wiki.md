---
tags: sudo, права, root, файлы
---
# sudo — права администратора на одну команду

В Linux у каждого пользователя свои границы: свои файлы он меняет как хочет, а в системные
каталоги (`/etc`, `/usr`, `/home` целиком) писать не может. Без границ есть только один —
**root**, суперпользователь. А `sudo` (superuser do) одалживает тебе его права ровно на одну
команду.

## Кто ты и где твои границы

    $ id
    uid=1000(anya) gid=1000(anya) groups=1000(anya),24(cdrom),25(floppy),27(sudo),29(audio),...

`uid=1000` — твой номер, у root он всегда `0`. Группа `sudo` в списке — знак, что тебе
разрешено пользоваться `sudo` (в Debian так и настроено: кто в группе `sudo`, тот может всё).

Попробуй создать что-нибудь в системном каталоге — получишь отказ:

    $ touch /etc/report.txt
    touch: cannot touch '/etc/report.txt': Permission denied
    $ ls -ld /etc
    drwxr-xr-x 157 root root 12288 Nov  4 02:03 /etc

Каталог принадлежит root, и писать (`w`) в нём может только владелец. Про буквы `rwx` —
в [wiki про chmod](/web/wiki/bunnyton/chmod-basics).

## touch и «полная информация» о файле

`touch` создаёт пустой файл (а если файл есть — просто обновляет ему время изменения).
Посмотреть, что за файл получился, — `ls -l`, «длинный» формат:

    $ touch report.txt
    $ ls -l report.txt
    -rw-rw-r-- 1 anya anya 0 Nov  4 02:14 report.txt

Слева направо: права, число ссылок, **владелец**, **группа**, размер в байтах, время
изменения, имя. Ещё подробнее — `stat`:

    $ stat report.txt
      File: report.txt
      Size: 0         	Blocks: 0          IO Block: 4096   regular empty file
    Access: (0664/-rw-rw-r--)  Uid: ( 1000/    anya)   Gid: ( 1000/    anya)
    Modify: 2026-11-04 02:14:15.758137505 +0300

Файл, созданный через `sudo`, принадлежит уже не тебе, а root — команду ведь выполнял он.

## Как работает sudo

    sudo команда аргументы…

- пароль спрашивается **твой**, а не root'а, и запоминается минут на 15 — следующие `sudo`
  его не спросят;
- кому что можно, написано в `/etc/sudoers` (а он, конечно, сам закрыт от чтения):

      $ ls -l /etc/sudoers /usr/bin/sudo
      -r--r----- 1 root root   1714 Jun 30  2025 /etc/sudoers
      -rwsr-xr-x 1 root root 306456 Apr 11  2026 /usr/bin/sudo

  `s` на месте `x` у владельца — бит setuid: программа запускается с правами своего владельца,
  то есть root. Так `sudo` и получает власть, а потом решает, давать ли её тебе;
- каждый вызов `sudo` записывается в системный журнал — кто, когда и что.

Полезные приёмы: `sudo -i` — открыть оболочку root (выход — `exit`), `sudo -l` — что тебе
разрешено, `sudo !!` — повторить прошлую команду, но уже с `sudo`.

## Ловушка: sudo действует только на одну команду

    $ bash -c 'echo hi > /etc/greeting'
    bash: line 1: /etc/greeting: Permission denied

С `sudo echo hi > /etc/greeting` будет то же самое: перенаправление `>` делает твоя оболочка,
ещё до запуска `sudo`, а у неё прав нет. Пишут так: `echo hi | sudo tee /etc/greeting`.

## Удаление: важны права на каталог

Удалить файл — значит вычеркнуть его из каталога. Поэтому нужен `w` не на файл, а на
**каталог**, где он лежит:

    $ mkdir shelf; echo hi > shelf/book.txt; chmod 555 shelf
    $ rm -f shelf/book.txt
    rm: cannot remove 'shelf/book.txt': Permission denied
    $ ls -ld shelf
    dr-xr-xr-x 2 anya anya 60 Nov  4 02:14 shelf

Файл твой, а удалить нельзя: каталог закрыт на запись.

## rm -rf / и защита корня

`rm -r` удаляет каталог со всем содержимым, `-f` — без вопросов и молча. Вместе с `sudo` это
самая разрушительная команда в системе: `/` — корень, в нём всё. Поэтому GNU `rm` сам
отказывается удалять корень — так он устроен по умолчанию:

    $ man rm
       --no-preserve-root
              do not treat '/' specially

       --preserve-root[=all]
              do not remove '/' (default); ...

Но защита только от корня: `sudo rm -rf /etc` или `rm -rf ~` с лишним пробелом
(`rm -rf ~ /tmp/x`) никто не остановит. Перед `sudo rm -r` всегда перечитай строку.

## Где это пригодится

- установка программ: `sudo apt install …` — см. [apt](/web/wiki/bunnyton/apt-update);
- правка системных настроек в `/etc`, запуск и остановка служб: `sudo systemctl restart …`;
- общее правило: работай обычным пользователем, `sudo` — только для конкретной команды.

## Источники

- [sudo(8) на man7.org](https://man7.org/linux/man-pages/man8/sudo.8.html) — все ключи.
- [sudo(8) по-русски — manpages.debian.org](https://manpages.debian.org/trixie/sudo/sudo.8.ru.html)
- [Sudo — ArchWiki (русский)](https://wiki.archlinux.org/title/Sudo_(Русский)) — настройка
  `/etc/sudoers`, советы и грабли.
- [sudo — Debian Wiki](https://wiki.debian.org/sudo) — как это устроено именно в Debian.
- [rm(1) на man7.org](https://man7.org/linux/man-pages/man1/rm.1.html) — про `--preserve-root`.
- [xkcd 149 «Sandwich»](https://xkcd.com/149/) — классика про sudo.

---
tags: apt, dpkg, пакеты, deb
---
# .deb-пакеты и dpkg

Всё, что ставит `apt`, приходит в виде `.deb`-файлов: apt скачивает их из репозитория и
передаёт установщику пониже — `dpkg`. Иногда `.deb` лежит прямо на сайте программы (Chrome,
VS Code, Discord, Zoom) — тогда его скачивают руками и ставят из файла. Основы apt — в
[wiki про apt](/web/wiki/bunnyton/apt-update).

## Скачать файл: wget

`wget адрес` скачивает файл в текущий каталог под тем же именем (`-O имя` — под другим,
`-q` — молча):

    $ wget http://ftp.debian.org/debian/pool/main/c/cowsay/cowsay_3.03+dfsg2-8_all.deb -O cow2.deb
    ...
    2026-11-04 02:29:53 (503 KB/s) - ‘cow2.deb’ saved [21372/21372]

Имя файла — само описание: `пакет_версия_архитектура.deb`. `amd64` — для обычных 64-битных
процессоров Intel/AMD, `all` — подходит любой архитектуре (скрипты, данные).
Пакет из репозитория можно скачать и без адреса: `apt-get download cowsay`.

## Что внутри .deb

Это обычный архив из трёх частей:

    $ ar t cowsay_3.03+dfsg2-8_all.deb
    debian-binary
    control.tar.xz
    data.tar.xz

`control` — описание и зависимости, `data` — сами файлы программы. Заглянуть можно, ничего
не устанавливая:

    $ dpkg-deb -I cow2.deb
     new Debian package, version 2.0.
     ...
     Package: cowsay
     Version: 3.03+dfsg2-8
     Architecture: all
     Depends: libtext-charwidth-perl, perl:any
     ...
    $ dpkg-deb -c cow2.deb | head -4
    drwxr-xr-x root/root         0 2020-05-11 09:43 ./
    drwxr-xr-x root/root         0 2020-05-11 09:43 ./usr/
    drwxr-xr-x root/root         0 2020-05-11 09:43 ./usr/games/
    -rwxr-xr-x root/root      4664 2020-05-11 09:43 ./usr/games/cowsay

Строка `Depends` — главное: без этих пакетов программа работать не будет.

## Два уровня: dpkg и apt

| | dpkg | apt |
|---|---|---|
| что умеет | поставить, снять, перечислить **один** `.deb` | искать, скачивать, разбирать зависимости |
| зависимости | только **проверяет** | сам **достаёт** из репозиториев |
| откуда пакеты | файл на диске | репозитории (и файлы тоже) |

`dpkg -i файл.deb` ставит ровно этот файл. Если зависимостей в системе нет, он распакует
пакет, но настраивать не станет и напишет `dependency problems` — пакет останется
полуустановленным. Это не установка, а повод доделать её средствами apt. Как именно — подскажут
сам вывод apt и поиск: «debian install deb file» — один из самых частых вопросов в интернете.

Как и apt, dpkg без root ничего не меняет:

    $ dpkg -i cowsay_3.03+dfsg2-8_all.deb
    dpkg: error: requested operation requires superuser privilege

## Проверить, что пакет встал

Состояние пакета знает dpkg:

    $ dpkg-query -W -f='${Status}\n' htop
    install ok installed
    $ dpkg-query -W -f='${Status}\n' cowsay
    dpkg-query: no packages found matching cowsay

`install ok installed` — пакет распакован **и** настроен. Полуустановленный покажет
`unpacked` или `half-configured`. Короче — `dpkg -l имя`, где `ii` в начале строки значит
«стоит».

Какие файлы принёс пакет и из какого пакета файл:

    $ dpkg -L htop | grep bin
    /usr/bin
    /usr/bin/htop
    $ dpkg -S /usr/bin/htop
    htop: /usr/bin/htop

## Осторожно с чужими .deb

Пакет ставится от root, и его скрипты установки выполняются от root. `.deb` с непонятного
сайта — то же, что запустить чужую программу с полными правами. Бери пакеты только у
производителя или из репозитория. И помни: `.deb` из файла сам не обновляется — разве что
программа при установке подключает свой репозиторий (так делают Chrome и VS Code; про
репозитории — в [apt-add-repo](/web/wiki/bunnyton/apt-add-repo)).

## Источники

- [dpkg(1) по-русски — manpages.debian.org](https://manpages.debian.org/trixie/dpkg/dpkg.1.ru.html)
- [dpkg-deb(1) по-русски](https://manpages.debian.org/trixie/dpkg/dpkg-deb.1.ru.html) —
  заглянуть в `.deb` без установки.
- [deb — Debian Wiki (русский)](https://wiki.debian.org/ru/deb) — формат пакета.
- [wget(1) на man7.org](https://man7.org/linux/man-pages/man1/wget.1.html)

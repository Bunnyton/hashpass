---
tags: fhs, каталоги, etc, proc, система
---
# Где что лежит: карта файловой системы

В Linux одно дерево каталогов, и начинается оно с корня `/`. Второй диск, флешка, сетевая папка,
сведения о процессоре — всё это каталоги и файлы где-то в этом дереве. Где что лежит, описано в
стандарте **FHS** (Filesystem Hierarchy Standard), поэтому на Debian, Ubuntu, Fedora и почти на любом
сервере порядок один и тот же. Выучил карту один раз — не теряешься на чужой машине.

## Корень

Так выглядит корень консоли курса:

    $ ls -l /
    lrwxrwxrwx   1 root root    7 Jul  4 12:05 bin -> usr/bin
    drwxr-xr-x   2 root root 4096 Jul  4 12:05 boot
    drwxr-xr-x   8 root root  480 Nov  4 02:41 dev
    drwxr-xr-x   1 root root 4096 Nov  4 02:41 etc
    drwxr-xr-x   3 root root 4096 Nov  2 14:04 home
    lrwxrwxrwx   1 root root    7 Jul  4 12:05 lib -> usr/lib
    lrwxrwxrwx   1 root root    9 Jul  4 12:05 lib64 -> usr/lib64
    drwxr-xr-x   2 root root 4096 Aug 24 03:00 media
    drwxr-xr-x   2 root root 4096 Aug 24 03:00 mnt
    drwxr-xr-x   3 root root 4096 Nov  2 14:05 opt
    dr-xr-xr-x 548 root root    0 Nov  4 02:41 proc
    drwx------   3 root root 4096 Nov  2 14:03 root
    drwxr-xr-x  11 root root  240 Nov  4 02:41 run
    lrwxrwxrwx   1 root root    8 Jul  4 12:05 sbin -> usr/sbin
    drwxr-xr-x   2 root root 4096 Aug 24 03:00 srv
    dr-xr-xr-x  13 root root    0 Nov  2 20:49 sys
    drwxrwxrwt   2 root root   40 Nov  4 02:41 tmp
    drwxr-xr-x  12 root root 4096 Sep  2 20:34 usr
    drwxr-xr-x   1 root root 4096 Nov  4 02:41 var

| Каталог | Что там | Когда туда смотрят |
|---|---|---|
| `/etc` | настройки системы и программ, текстовые файлы | поменять поведение программы, узнать, как она настроена |
| `/var` | то, что меняется во время работы: журналы (`/var/log`), очереди почты и печати, базы (`/var/lib`), кэш | что случилось, где данные службы |
| `/usr` | программы (`/usr/bin`), библиотеки (`/usr/lib`), документация и man (`/usr/share`) | где установленная программа |
| `/usr/local` | то, что админ поставил сам, мимо пакетов | свои скрипты для всех пользователей |
| `/opt` | сторонние программы, поставленные целиком в один каталог | программы вендоров, которых нет в репозитории |
| `/home` | домашние каталоги пользователей | свои файлы |
| `/root` | домашний каталог root | — |
| `/tmp`, `/var/tmp` | временные файлы | не храни там ничего важного |
| `/proc`, `/sys` | окно в ядро: процессы, железо, настройки ядра | сведения о системе |
| `/dev` | устройства: диски, терминалы, `/dev/null` | — |
| `/run` | данные, нужные только до перезагрузки: PID-файлы, сокеты | — |
| `/boot` | ядро и загрузчик | — |
| `/media`, `/mnt` | точки подключения флешек и временно подключённых дисков | — |
| `/srv` | данные, которые сервер раздаёт: сайты, FTP | — |

## /etc — настройки и сведения о системе

Почти всё, что система «знает» о себе постоянного, лежит в `/etc` обычным текстом. Имена говорящие:

    $ cat /etc/hostname
    hashpass
    $ cat /etc/debian_version
    13.6

Подробнее о системе — в `/etc/os-release`: название, версия, кодовое имя (`trixie`). Его читают
скрипты, которым важна версия, — например, установщики, которые выбирают нужный пакет.

Пользователи — строки в `/etc/passwd`, по одной на пользователя, поля через двоеточие:

    student:x:1000:1000::/home/student:/bin/bash

Имя, `x` (пароль хранится не здесь, а в `/etc/shadow`), номер пользователя (UID), номер основной
группы (GID), комментарий (здесь пусто), домашний каталог, оболочка. Подробнее — в задании про учётки.

## /proc — файлы, которых нет на диске

`/proc` — не каталог на диске, а окно в ядро. Каждый файл там ядро сочиняет в момент чтения:

    $ ls -l /proc/cpuinfo
    -r--r--r-- 1 root root 0 Nov  4 02:42 /proc/cpuinfo
    $ cat /proc/cpuinfo | head -3
    processor	: 0
    vendor_id	: GenuineIntel
    cpu family	: 6

Размер 0, а внутри — десятки строк. Так же устроены `/proc/meminfo` (память), `/proc/uptime`
(сколько работает система), `/proc/<PID>/` — каталог на каждый процесс. Утилиты `free`, `uptime`,
`ps`, `top` ничего не знают сами — они читают `/proc`.

## /bin — ссылка на /usr/bin

Когда-то `/bin` и `/usr/bin` были разными: в `/bin` — самое нужное для загрузки, а `/usr` часто
лежал на другом диске и подключался позже. Сейчас диски большие, и в Debian (с версии 12)
каталоги объединены: `/bin`, `/sbin`, `/lib` — просто символьные ссылки в `/usr`. Старые пути
продолжают работать — скрипты с `#!/bin/sh` не ломаются.

## Где это пригодится

- на незнакомом сервере: настройки — в `/etc`, журналы — в `/var/log`, данные служб — в `/var/lib`;
- кончилось место — первые подозреваемые `/var/log`, `/var/lib`, `/home`, `/tmp`;
- «куда поставилась программа?» — `/usr/bin`, если из пакета; `/usr/local/bin`, если руками;
  `/opt/<имя>`, если от вендора.

## Источники

- [Filesystem Hierarchy Standard 3.0](https://refspecs.linuxfoundation.org/FHS_3.0/fhs/index.html) — сам стандарт.
- `man 7 hier` — [на man7.org](https://man7.org/linux/man-pages/man7/hier.7.html): описание каждого каталога.
- `man 5 passwd` — [на man7.org](https://man7.org/linux/man-pages/man5/passwd.5.html): поля /etc/passwd.
- `man 5 proc` — [на man7.org](https://man7.org/linux/man-pages/man5/proc.5.html): что есть в /proc.
- [UsrMerge — Debian Wiki](https://wiki.debian.org/UsrMerge) — почему /bin стал ссылкой.

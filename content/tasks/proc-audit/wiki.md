---
tags: процессы, ps, pstree, proc
---
# Процессы: PID, родители, дерево и службы

Что работает на сервере и от чьего имени — первый вопрос любого аудита, отладки или расследования
взлома. Здесь — что такое процесс, как процессы связаны друг с другом и чем на них смотреть.

## Программа и процесс

**Программа** — файл на диске: `/usr/bin/sleep`. Сама по себе она ничего не делает.
**Процесс** — запущенная программа. Ядро при запуске:

1. выделяет память и загружает туда код;
2. даёт номер — **PID**;
3. запоминает родителя — **PPID**;
4. запоминает, от чьего имени он работает (**USER**), и терминал.

Одна программа может работать многими процессами: три открытых терминала — три `bash`, у
каждого свой PID и своя память.

## Дерево процессов

Новый процесс всегда запускает уже существующий: набрал `ls` — его запустил твой `bash`. Так все
процессы складываются в **дерево**. На вершине — **PID 1**, первая программа после загрузки ядра;
в современных Linux это **systemd**:

    $ ps -o pid,ppid,stat,comm -p 1
        PID    PPID STAT COMMAND
          1       0 Ss   systemd

Дерево целиком рисует `pstree` из пакета **psmisc**. Пакета может не быть — тогда его ставят
через apt, как любой другой (сначала обновив список пакетов). С ключом `-p` pstree пишет номера:

    $ pstree -p 399469
    kitchen(399469)-+-sleep(399471)
                    |-sleep(399472)
                    `-sleep(399473)

Ещё полезно: `pstree -s PID` — путь от PID 1 до этого процесса, `pstree имя_пользователя` —
только его процессы. В psmisc ещё `killall` (сигнал по имени) и `fuser` (кто держит файл или
порт).

## ps — снимок процессов

`ps` без ключей показывает только процессы твоего терминала. Все — два популярных вида:

    $ ps aux | head -4
    USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
    root           1  0.0  0.0  25224 12004 ?        Ss   Nov02   0:09 /sbin/init
    root           2  0.0  0.0      0     0 ?        S    Nov02   0:00 [kthreadd]
    root           3  0.0  0.0      0     0 ?        S    Nov02   0:00 [pool_workqueue_release]

    $ ps -ef | head -3
    UID          PID    PPID  C STIME TTY          TIME CMD
    root           1       0  0 Nov02 ?        00:00:09 /sbin/init
    root           2       0  0 Nov02 ?        00:00:00 [kthreadd]

- **STAT**: R — работает, S — спит и ждёт, T — остановлен, Z — зомби; `s` — глава сессии;
- **TTY**: `?` — терминала нет, это служба или демон;
- в квадратных скобках — **потоки ядра** (`[kthreadd]`). В контейнере их не видно: ядро общее с
  хостом;
- в `ps -ef` есть **PPID** — номер родителя.

Длинный список сужают конвейером: `ps aux | grep cron`. А можно попросить ровно нужные
столбцы — `-o`, и выбрать процессы по имени — `-C`:

    $ ps -o pid,user,comm -C avahi-daemon
        PID USER     COMMAND
       1014 avahi    avahi-daemon
       1064 avahi    avahi-daemon

Грабли: длинные имена пользователей ps обрезает до 7 букв и плюса. Ширину задают двоеточием:

    $ ps -o user,comm -C dbus-daemon
    USER     COMMAND
    message+ dbus-daemon
    anya     dbus-daemon
    anya     dbus-daemon
    $ ps -o user:20,comm -C dbus-daemon
    USER                 COMMAND
    messagebus           dbus-daemon
    anya                 dbus-daemon
    anya                 dbus-daemon

Знак `=` после имени столбца убирает заголовок: `ps -o pid= -C cron` — удобно в скриптах.

## Службы и системные пользователи

В списке много того, чего ты не запускал: `systemd-journald` (журналы), `dbus-daemon`
(почтальон между программами), `cron`, `sshd`. Это **службы** — фоновые программы без
терминала, их запускает и сторожит systemd. Подробно — в [задании services](/web/wiki/bunnyton/services).

Службы обычно работают **не от root**, а от **системных пользователей**: `messagebus`, `avahi`,
`www-data`, `postgres`, `daemon`. Войти под таким именем нельзя — это пропуск для одной
программы. Взломают её — взломщик получит права пропуска, а не всей системы. Поэтому служба
от root — повод присмотреться.

## /proc — процессы как файлы

Откуда ps всё это знает? Ядро показывает каждый процесс каталогом `/proc/PID`:

    $ grep -E '^(Name|State|PPid|Uid)' /proc/407792/status
    Name:	nap
    State:	S (sleeping)
    PPid:	407790
    Uid:	1000	1000	1000	1000
    $ tr '\0' ' ' < /proc/407792/cmdline
    ./nap 100
    $ readlink /proc/407792/exe
    /tmp/tmp.ubP49i3NpU/nap

Это не файлы на диске: ядро сочиняет их в момент чтения. `ps`, `top`, `pstree`, `htop` — просто
удобные читатели `/proc`. Uid тут числом: имя по нему — `getent passwd 1000`.

## Источники

- [man ps (man7.org)](https://man7.org/linux/man-pages/man1/ps.1.html) — все столбцы и ключи.
- [man pstree (man7.org)](https://man7.org/linux/man-pages/man1/pstree.1.html) — дерево.
- [man proc(5) (man7.org)](https://man7.org/linux/man-pages/man5/proc.5.html) — что лежит в
  `/proc/PID`.
- [man fuser (man7.org)](https://man7.org/linux/man-pages/man1/fuser.1.html) — ещё один
  инструмент psmisc.
- [Процесс (информатика) — Википедия](https://ru.wikipedia.org/wiki/Процесс_(информатика)) —
  понятие по-русски.

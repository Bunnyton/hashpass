---
tags: процессы, память, fork, copy-on-write
---
# fork и copy-on-write: сколько памяти на самом деле

Шесть процессов, у каждого в `top` по 256 МБ, — это полтора гигабайта? Не обязательно.
Чтобы понять почему, надо знать, как рождаются процессы и как ядро экономит память.

## fork + exec — как рождается процесс

Новый процесс в Linux появляется в два хода:

1. **fork** — процесс делает копию самого себя: новый PID, а программа, память, открытые
   файлы — те же;
2. **exec** — копия заменяет свою программу на другую; PID остаётся.

Видно прямо в оболочке. `exec` заменяет bash на `ps` — номер тот же, имя уже другое:

    $ bash -c 'echo "я bash, мой PID $$"; ps -o pid,ppid,comm -p $$; exec ps -o pid,ppid,comm -p $$'
    я bash, мой PID 439422
        PID    PPID COMMAND
     439422  439421 bash
        PID    PPID COMMAND
     439422  439421 ps

Так запускается всё: bash делает fork+exec для каждой твоей команды, systemd — для каждой
службы. Бывает и fork **без** exec: копии остаются той же программой и делят работу — так
устроены веб-серверы и базы данных.

## VIRT, RES, SHR — что показывают top и ps

    VIRT (VSZ)  сколько памяти процесс «застолбил», включая нетронутое
    RES  (RSS)  сколько реально лежит в оперативной памяти и видно процессу
    SHR         часть RES, которую можно делить с другими (библиотеки, файлы)

Ловушка: одна и та же страница памяти может быть видна многим процессам, и каждый посчитает
её в своём RES. Поэтому **сумма RES врёт**.

## Copy-on-write

Память делится на **страницы**:

    $ getconf PAGESIZE
    4096

fork не копирует страницы, а даёт ребёнку доступ к тем же самым и помечает их «только для
чтения». Пока оба читают — страница одна на всех. Как только кто-то пишет, ядро тихо делает
копию **этой** страницы — личную для писавшего. Это copy-on-write (COW): копия только при
записи и только того, во что писали. Поэтому fork почти бесплатный.

## Проверим: четыре близнеца

Небольшая программа на Python заняла 100 МБ, сделала три fork, и третий ребёнок переписал
весь массив. Запустим её как службу (пользовательскую, через `systemd-run --user`):

    $ ps -o pid,ppid,rss,comm --ppid 404159 -p 404159
        PID    PPID   RSS COMMAND
     404159    2629 111892 python3
     404161  404159 107788 python3
     404162  404159 107788 python3
     404163  404159 108044 python3

Сумма RES — около 435 МБ. А что говорит systemd, который считает настоящие страницы всех
процессов службы (её cgroup)?

    $ systemctl --user status mytest-twins --no-pager
    ● mytest-twins.service - [systemd-run] /usr/bin/python3 /tmp/tmp.4tsN4FTt58/cowdemo/twins.py
         Active: active (running) since Wed 2026-11-04 02:19:42 MSK; 5s ago
          Tasks: 4 (limit: 18329)
         Memory: 205.5M (peak: 205.6M)
    ...

205 МБ: 100 общих на всех + 100 личных у того, кто писал.

## smaps_rollup — чья память своя

Подробный счёт памяти процесса ядро пишет в `/proc/<PID>/smaps_rollup`:

    Rss             то же, что RES: всё, что видно процессу
    Pss             своя доля: общая страница делится поровну между всеми, кто её видит
    Shared_Dirty    изменённые страницы, которые он делит с другими
    Private_Dirty   изменённые страницы, которые есть только у него

Родитель из примера:

    $ grep -E '^(Rss|Pss|Shared_Dirty|Private_Dirty):' /proc/404159/smaps_rollup
    Rss:              111892 kB
    Pss:               35944 kB
    Shared_Dirty:     105276 kB
    Private_Dirty:       124 kB

А ребёнок, который переписал массив (из другого прогона той же программы):

    Rss:              108052 kB
    Pss:              103535 kB
    Shared_Dirty:       2872 kB
    Private_Dirty:    102544 kB

RES у обоих почти одинаковый, а `Private_Dirty` отличается в сотни раз. Сложи `Pss`
всех процессов — получишь честную сумму.

## Где это встречается

- **redis** сохраняет базу на диск через fork: ребёнок пишет снимок, а копируются только
  страницы, которые родитель успел поменять за это время;
- **PostgreSQL, nginx, Apache** — рабочие процессы fork-ами от общего родителя;
- **Android** запускает каждое приложение fork-ом заранее прогретого процесса zygote;
- `kill PID` останавливает один процесс; `kill -1` — «все процессы, какие можешь», включая
  твою же оболочку. Как читать `top` — в [wiki про top](/web/wiki/bunnyton/top).

## Источники

- [fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html) и
  [execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html) на man7.org.
- [proc_pid_smaps(5)](https://man7.org/linux/man-pages/man5/proc_pid_smaps.5.html) — все поля
  smaps и smaps_rollup.
- [The /proc Filesystem — документация ядра](https://www.kernel.org/doc/html/latest/filesystems/proc.html)
  — Rss, Pss, Private/Shared.
- [Копирование при записи — Википедия](https://ru.wikipedia.org/wiki/Копирование_при_записи)
- [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
  — как fork и COW используют на практике.

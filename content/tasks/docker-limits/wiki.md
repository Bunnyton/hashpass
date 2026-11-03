---
tags: docker, cgroups, лимиты, память, процессор
---
# Лимиты контейнера: память и процессор

Контейнеры на одной машине делят её память и процессор. По умолчанию пределов нет: один
прожорливый контейнер заберёт всё, и соседям — сайту, базе — не останется ничего. Пределы
ставит ядро, а docker лишь передаёт ему цифры.

## cgroups — кто считает и ограничивает

**cgroups** (control groups) — механизм ядра Linux:

1. Ядро собирает процессы в группу.
2. Считает, сколько памяти, процессорного времени, процессов группа тратит.
3. Если группе задан предел, больше не даёт.

Docker заводит группу каждому контейнеру сам. Её настройки видны изнутри, как обычные файлы
в `/sys/fs/cgroup`:

    $ docker run --rm alpine cat /sys/fs/cgroup/memory.max
    max
    $ docker run --rm --memory 32m alpine cat /sys/fs/cgroup/memory.max
    33554432

`max` — без предела, 33554432 байта — 32 МиБ. Те же группы использует systemd для служб, а
Kubernetes — для подов.

## Память

Пределы задают ключами `docker run`; все они перечислены в `docker run --help`. Объём пишут
числом с единицей: `k`, `m`, `g` (`512m`, `2g`). Число без буквы — это байты, и docker
напомнит:

    $ docker run --rm --memory 32 alpine true
    docker: Error response from daemon: Minimum memory limit allowed is 6MB
    $ docker run --rm --memory 32x alpine true
    invalid argument "32x" for "-m, --memory" flag: invalid suffix: 'x'

## Что бывает, когда память кончилась

`tail /dev/zero` ищет конец бесконечного файла без переводов строки и копит его в памяти —
идеальный пожиратель:

    $ docker run --name my-test-hog --memory 32m alpine sh -c 'echo "ем память"; tail /dev/zero'
    ем память
    $ echo $?
    137
    $ docker ps -a --filter name=my-test-hog --format 'table {{.Names}}\t{{.Status}}'
    NAMES         STATUS
    my-test-hog   Exited (137) Less than a second ago

Что произошло:

1. Контейнер упёрся в предел — ядро не даёт ему больше ни байта.
2. Приходит **OOM killer** (out of memory) и завершает процесс сигналом `SIGKILL` (№ 9) — без
   предупреждения: ни сохранить, ни дописать журнал.
3. Код выхода процесса, убитого сигналом, — 128 + номер сигнала. 128 + 9 = **137**.

Тот же код бывает и от `kill -9` без всякой памяти, а мягкий `SIGTERM` (№ 15) даёт 143:

    $ docker run --rm alpine sh -c 'sleep 600 & kill -9 $!; wait $!; echo "код: $?"'
    код: 137
    $ docker run --rm alpine sh -c 'sleep 600 & kill -15 $!; wait $!; echo "код: $?"'
    код: 143

Поэтому подтверждают по `docker inspect` — там есть поле `OOMKilled`:

    $ docker inspect -f 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}' my-test-hog
    OOMKilled=true ExitCode=137

Упал один контейнер — а не случайный процесс на сервере. Без предела ядро тоже вызвало бы OOM
killer, но выбирало бы жертву по всей машине.

## Процессор

Процессор ограничивают **долей ядер**: `1` — одно ядро целиком, `1.5` — полтора, `0.25` —
четверть. Внутри это тоже cgroups: из каждых 100 мс группе разрешено работать только часть, а
остальное время она стоит на паузе:

    $ docker run --rm --cpus 0.25 alpine cat /sys/fs/cgroup/cpu.max
    25000 100000

25 000 мкс работы из каждых 100 000. Бесконечный цикл с таким пределом:

    $ docker run -d --name my-test-spin --cpus 0.25 --memory 64m alpine sh -c 'while :; do :; done'
    $ docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' my-test-spin
    NAME           CPU %     MEM USAGE / LIMIT   MEM %     PIDS
    my-test-spin   24.97%    408KiB / 64MiB      0.62%     1

`docker stats` без `--no-stream` — живая таблица, как `top` для контейнеров (выход —
`Ctrl+C`). 100 % там — одно ядро целиком; на многоядерной машине без предела бывает и 400 %.

Предел у работающего контейнера можно поменять без перезапуска — `docker update`:

    $ docker update --cpus 0.5 my-test-spin
    $ docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' my-test-spin
    NAME           CPU %     MEM USAGE / LIMIT
    my-test-spin   49.77%    408KiB / 64MiB

## Ещё пределы

    --memory-swap 1g     память + своп вместе
    --cpuset-cpus 0,1    работать только на ядрах 0 и 1
    --pids-limit 100     не больше 100 процессов — защита от «форк-бомбы»

    $ docker run --rm --pids-limit 5 alpine sh -c 'for i in 1 2 3 4 5 6; do sleep 30 & done'
    sh: can't fork: Resource temporarily unavailable

## Где пригодится

- на сервере, где рядом живут сайт и база, — каждому сервису свой предел;
- найти, кто съел сервер, — `docker stats`;
- в compose те же пределы пишут в `deploy.resources.limits`, в Kubernetes — в `resources.limits`.

## Источники

- [Resource constraints — документация Docker](https://docs.docker.com/engine/containers/resource_constraints/)
  — все ключи памяти и процессора.
- [docker container stats](https://docs.docker.com/reference/cli/docker/container/stats/)
- `man 7 cgroups` — [на man7.org](https://man7.org/linux/man-pages/man7/cgroups.7.html).
- [Control Group v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) —
  документация ядра: memory.max, cpu.max и остальные файлы.
- `man 7 signal` — [на man7.org](https://man7.org/linux/man-pages/man7/signal.7.html): номера
  сигналов, SIGKILL и SIGTERM.
- [cgroups — Википедия](https://ru.wikipedia.org/wiki/Cgroups)

---
tags: docker, ядро, процессы, namespaces
---
# Контейнер изнутри: общее ядро и пространства имён

Контейнер часто называют «лёгкой виртуалкой». Это не так, и от разницы зависит, сколько
ресурсов ему нужно и где его можно запустить.

    виртуальная машина            контейнер
    своё «железо» и своё ядро     ядро машины, общее на всех
    гигабайты, минуты             мегабайты, доли секунды
    любая ОС внутри               только Linux на Linux

## Ядро одно на всех

**Ядро** — главная программа системы: оно управляет памятью, процессами, дисками и сетью.
Всё остальное — `bash`, `ls`, `nginx` — программы, которые просят ядро о работе. Дистрибутив
(Debian, Alpine, Ubuntu) — это набор программ и файлов **вокруг** ядра.

`uname` печатает сведения о ядре. Сравним машину и два разных контейнера:

    $ uname -a
    Linux anya 6.12.105+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.105-1 (2026-08-24) x86_64 GNU/Linux
    $ docker run --rm alpine uname -a
    Linux 8d04cb334b9e 6.12.105+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.105-1 (2026-08-24) x86_64 Linux
    $ docker run --rm busybox uname -a
    Linux fa9d93009bda 6.12.105+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.105-1 (2026-08-24) x86_64 GNU/Linux

Внутри Alpine — а ядро собрано Debian: то же самое, что у машины. Разные только имена машин
(у контейнеров — их ID). Отдельные поля `uname` выбирают ключами — `uname --help`.

Отсюда следствия:

- контейнер с Linux не запустить на «голой» Windows или macOS — Docker Desktop там тайком
  поднимает маленькую виртуалку с Linux;
- программа, которой нужно ядро новее, чем на машине, в контейнере не заработает;
- модули ядра и его настройки (`sysctl`) — общие: контейнер их не выбирает.

## Контейнер — это процесс машины

Запустим в фоне контейнер, который просто спит, и поищем его среди процессов машины:

    $ docker run -d --name mytest-sleeper busybox sleep 777
    $ ps -ef | grep "sleep 777"
    root      407890  407867  3 02:20 ?        00:00:00 sleep 777

Вот он — обычный процесс с обычным номером, родитель — служебный процесс docker. Тот же
список процессов контейнера, но глазами машины, даёт `docker top`, а номер на машине —
`docker inspect`:

    $ docker top mytest-sleeper
    UID                 PID                 PPID                C                   STIME               TTY                 TIME                CMD
    root                407890              407867              3                   02:20               ?                   00:00:00            sleep 777
    $ docker inspect -f '{{.State.Pid}}' mytest-sleeper
    407890

## Изнутри — PID 1

А изнутри контейнер видит только себя. `ps` в одноразовом контейнере:

    $ docker run --rm busybox ps
    PID   USER     TIME  COMMAND
        1 root      0:00 ps

Ни одного процесса машины — и сам `ps` первый, PID 1. Один процесс, два номера: снаружи
большой, внутри — 1. PID 1 в Linux особенный: он не получает сигналы, на которые сам не
поставил обработчик, — поэтому `sleep` в контейнере не умирает от Ctrl+C.

## Пространства имён (namespaces)

Свой мир процессу делает ядро. У Linux есть **пространства имён**: каждое отвечает за одну
часть системы, и ядро может показать процессу её отдельную версию.

    pid     свой список процессов — внутри видно только себя
    mnt     своё дерево файлов — образ вместо диска машины
    net     своя сеть: свои адреса и порты
    uts     своё имя машины (hostname)
    ipc     свои очереди сообщений и общая память
    user    свои пользователи: root внутри — не root снаружи
    cgroup  своё дерево cgroups — групп с ограничениями памяти и процессора

У каждого процесса они видны в `/proc/<PID>/ns` — номер в скобках и есть пространство. Своя
оболочка на машине:

    $ readlink /proc/self/ns/pid /proc/self/ns/net /proc/self/ns/uts
    pid:[4026531836]
    net:[4026531840]
    uts:[4026531838]

И процесс в контейнере:

    $ docker run --rm alpine ls -l /proc/self/ns
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 ipc -> ipc:[4026535413]
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 mnt -> mnt:[4026535411]
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 net -> net:[4026535416]
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 pid -> pid:[4026535414]
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 user -> user:[4026531837]
    lrwxrwxrwx    1 root     root             0 Nov  3 23:20 uts -> uts:[4026535412]

(здесь показаны не все строки). Номера pid, net, uts, mnt — другие: у контейнера свои. А
`user` совпадает с машиной: на этом docker пространство пользователей не включено, и root в
контейнере — тот же root ядра. Это настройка (`userns-remap` или docker без root, как в
учебной консоли).

Своё имя машины — пространство uts в деле:

    $ docker run --rm --hostname mytest-box busybox hostname
    mytest-box

## Где это пригодится

- понять, почему «сколько памяти выделить контейнеру?» — вопрос про лимиты cgroups, а не про
  размер виртуалки;
- найти, какой контейнер грузит машину: `top` на машине покажет процесс, `docker top` и
  `docker inspect` свяжут его с контейнером;
- зайти в пространства имён чужого процесса без docker — `nsenter`, создать свои —
  `unshare`.

## Источники

- [namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html) и
  [pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html) — man7.org.
- [cgroups(7)](https://man7.org/linux/man-pages/man7/cgroups.7.html) — ограничения ресурсов.
- [Namespaces in operation, part 1](https://lwn.net/Articles/531114/) — классический цикл
  статей LWN.
- [Механизмы контейнеризации: namespaces](https://habr.com/ru/companies/selectel/articles/279281/)
  и [Глубокое погружение в Linux namespaces](https://habr.com/ru/articles/458462/) — по-русски.
- [docker container top](https://docs.docker.com/reference/cli/docker/container/top/) —
  справка.

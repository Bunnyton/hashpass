---
tags: docker, сеть, контейнеры, dns
---
# Сети docker: контейнеры по имени

Настоящий сервис редко живёт в одном контейнере: сайт отдельно, база отдельно, кэш отдельно.
Каждый — со своими программами, а между собой они говорят по сети, как два сервера: один
спрашивает по адресу, другой отвечает.

## Спросить из соседнего контейнера

Самая быстрая проверка — одноразовый контейнер рядом. В `busybox` нет curl, зато есть
`wget`; `-qO-` печатает страницу на экран вместо файла, а `--rm` уберёт контейнер после
проверки:

    docker run --rm busybox wget -qO- http://адрес/

Запустим «сервис» — nginx под именем `mytest-api`, без всяких `-p`: снаружи к нему ходить
не нужно.

    $ docker run -d --name mytest-api nginx:alpine
    $ docker run --rm busybox wget -qO- http://mytest-api/
    wget: bad address 'mytest-api'

## Сеть по умолчанию: адреса есть, имён нет

Контейнеры без ключей попадают в общую сеть `bridge`. Связь в ней есть, но только по
IP-адресам:

    $ docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' mytest-api
    172.17.0.3
    $ docker run --rm busybox wget -qO- http://172.17.0.3/ | grep title
    <title>Welcome to nginx!</title>

Работает — но адрес выдаётся при запуске и после перезапуска может стать другим. Вписывать
его в настройки — значит чинить их каждый раз.

## Своя сеть — своя адресная книга

В сетях, которые ты создаёшь сам, docker держит встроенный DNS: каждый контейнер доступен
остальным **по имени** (`--name`).

    $ docker network create mytest-net
    c16ac91a4ac165c9c1bb741cc67f934e28f4f04339e234f1aee759071ed26c92
    $ docker network connect mytest-net mytest-api
    $ docker run --rm --network mytest-net busybox wget -qO- http://mytest-api/ | grep title
    <title>Welcome to nginx!</title>

Кто отвечает на имена — видно через `nslookup`: DNS-сервер docker живёт по адресу 127.0.0.11
внутри каждого контейнера своей сети. (Два «Non-authoritative answer» — busybox спрашивает и IPv4,
и IPv6; второго адреса нет.)

    $ docker run --rm --network mytest-net busybox nslookup mytest-api
    Server:		127.0.0.11
    Address:	127.0.0.11:53

    Non-authoritative answer:

    Non-authoritative answer:
    Name:	mytest-api
    Address: 192.168.16.2

Два способа попасть в сеть:

- сразу при запуске — `docker run --network имя_сети …`;
- уже работающим — `docker network connect имя_сети контейнер`.

В сети должны быть **обе стороны** — и тот, кто спрашивает, и тот, кто отвечает. Контейнер
может состоять в нескольких сетях сразу и в каждой имеет свой адрес:

    $ docker inspect -f '{{range $n, $v := .NetworkSettings.Networks}}{{$n}} {{$v.IPAddress}}{{println}}{{end}}' mytest-api
    bridge 172.17.0.3
    mytest-net 192.168.16.2

## Наружу — только то, что нужно людям

Обычная схема: внутренние сервисы без `-p`, в своей сети, а наружу публикуется только вход —
сайт или API. Порт для браузера и сеть для соседей — независимые вещи, у контейнера могут
быть обе:

    $ docker run -d --name mytest-web --network mytest-net -p 18085:80 nginx:alpine
    $ docker ps --filter name=^mytest- --format 'table {{.Names}}\t{{.Ports}}\t{{.Networks}}'
    NAMES        PORTS                                       NETWORKS
    mytest-web   0.0.0.0:18085->80/tcp, [::]:18085->80/tcp   mytest-net
    mytest-api   80/tcp                                      bridge,mytest-net

`80/tcp` без стрелки — порт есть, но наружу не опубликован: к `mytest-api` ходят только соседи
по сети.

## Какие сети бывают

    $ docker network ls --filter name=^bridge$ --filter name=^host$ --filter name=^none$
    NETWORK ID     NAME      DRIVER    SCOPE
    6e4c32114a83   bridge    bridge    local
    9e3abe339f6e   host      host      local
    1354646b30f0   none      null      local

- `bridge` — сеть по умолчанию: адреса без имён.
- `host` — контейнер сидит прямо в сети машины, без изоляции и без `-p`.
- `none` — сети нет вовсе, только loopback.
- Свои сети (`docker network create`) — тоже драйвер `bridge`, но с именами.

Убрать сеть — `docker network rm`; пока к ней подключены контейнеры, docker откажет.
docker compose заводит такую сеть для каждого проекта сам — поэтому там сервисы с первого
раза видят друг друга по именам.

## Источники

- [Networking overview](https://docs.docker.com/engine/network/) — сети docker целиком
  (официальная документация).
- [Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/) — чем своя
  сеть отличается от сети по умолчанию, в том числе DNS.
- [docker network](https://docs.docker.com/reference/cli/docker/network/) — справка по
  командам `create`, `connect`, `ls`, `rm`.
- [Изучаем Docker, часть 2: термины и концепции](https://habr.com/ru/companies/ruvds/articles/439978/)
  — по-русски.

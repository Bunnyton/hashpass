---
tags: docker, compose, масштабирование, сеть, безопасность
---
# Compose: копии сервиса и сети

Одному контейнеру тяжело — запускают несколько **одинаковых**: копий (реплик) одного сервиса.
А чтобы взлом одного сервиса не открывал дорогу ко всем, сервисы разводят по разным сетям.
Здесь — как это делает compose.

## --scale: сколько копий

    docker compose up -d --scale web=3      # три контейнера сервиса web

Копии называются по номерам: `проект-web-1`, `-2`, `-3`. Остальные сервисы по-прежнему
обращаются к ним по имени сервиса — встроенный DNS отвечает адресами всех копий сразу:

    $ docker compose exec db nslookup web 127.0.0.11
    Server:		127.0.0.11
    …
    Name:	web
    Address: 192.168.16.4
    Name:	web
    Address: 192.168.16.3

## Один порт машины — одна копия

Все копии получают одинаковые настройки. Если записан один порт машины, его хотят все, а
достанется он одному:

    $ docker compose up -d --scale web=3        # ports: - "8470:80"
     …
     Container my-test-fair-web-1 Started
    Error response from daemon: … Bind for 0.0.0.0:8470 failed: port is already allocated
    $ docker compose ps -a
    NAME                 STATUS                  PORTS
    my-test-fair-web-1   Up Less than a second   0.0.0.0:8470->80/tcp
    my-test-fair-web-2   Created
    my-test-fair-web-3   Created

Для копий пишут **диапазон** портов машины — каждая займёт свободный из него:

    ports:
      - "9001-9004:80"      # до четырёх копий: 9001, 9002, 9003, 9004

Порядок не гарантирован — какая копия какой порт взяла, смотри в `ps`:

    $ docker compose ps
    NAME                 STATUS                  PORTS
    my-test-fair-web-1   Up Less than a second   0.0.0.0:8470->80/tcp
    my-test-fair-web-2   Up Less than a second   0.0.0.0:8472->80/tcp
    my-test-fair-web-3   Up Less than a second   0.0.0.0:8471->80/tcp

Если же сервису порт наружу не нужен (к нему ходят только соседи), ни диапазона, ни конфликта:
`ports` просто не пишут.

## Число копий — в файле

`--scale` живёт только в той команде, где его набрали. Следующий обычный `up` вернёт
описание из файла — одну копию:

    $ docker compose up -d
     Container my-test-fair-web-1 Running
     Container my-test-fair-web-2 Removed
     Container my-test-fair-web-3 Removed

Чтобы число жило в `compose.yaml`, его записывают полем `replicas` в разделе `deploy` у
сервиса. Раздел `deploy` пришёл из Docker Swarm — там же лимиты ресурсов
(`deploy.resources.limits`) и правила обновления. Тот же файл понимает `docker stack deploy`,
раскидывая реплики по нескольким серверам.

Перед репликами обычно ставят **балансировщик** (nginx, HAProxy, Traefik): он один слушает
порт и раздаёт запросы по копиям.

## Сети в compose

По умолчанию проекту заводится одна сеть, `проект_default`, и в ней все. Чтобы развести
сервисы:

1. Опиши сети в разделе `networks` — в корне файла, на одном уровне с `services`.
2. У сервиса в его собственном поле `networks` перечисли, где он состоит. Сервис в двух сетях —
   мост между ними.
3. Сети, которой нужна изоляция, добавь `internal: true`.

    services:
      db:
        networks: [back]
      api:
        networks: [back, front]   # мост
    networks:
      back:
        internal: true
      front:

Сеть без настроек (`front:`) — обычный мост docker. Имена у сетей — с приставкой проекта:

    $ docker network ls --filter name=my-test-fair --format 'table {{.Name}}\t{{.Driver}}\t{{.Internal}}'
    NAME                 DRIVER    INTERNAL
    my-test-fair_back    bridge    true
    my-test-fair_front   bridge    false

## Внутренняя сеть

**Внутренняя** сеть соединяет контейнеры между собой, но не выпускает наружу — ни в интернет,
ни на порты машины. Сервис только во внутренней сети соседей видит, а мир — нет:

    $ docker compose exec web wget -qO- http://db/          # web: в back и front
    данные
    $ docker compose exec db wget -qO- -T 3 http://example.org/   # db: только в back
    wget: bad address 'example.org'

А `web` в интернет выходит — через обычную сеть `front`. Поэтому сервису с проброшенным портом
нужна хотя бы одна обычная сеть: через внутреннюю порт машины до него не дойдёт.

Смысл — зоны доверия: взломают внешний сервис — у взломщика будет внутренняя сеть, но база из
неё не сможет ни скачать инструменты, ни отправить данные наружу.

Сети docker без compose — в [docker-network](/web/wiki/bunnyton/docker-network).

## Источники

- [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/) — ключ
  `--scale` и остальные.
- [Compose Deploy Specification](https://docs.docker.com/reference/compose-file/deploy/) —
  `replicas`, `resources` и всё в `deploy`.
- [Справочник networks](https://docs.docker.com/reference/compose-file/networks/) — сети
  верхнего уровня, `internal`, драйверы.
- [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/) — как сервисы
  находят друг друга.
- [Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/) — как устроен
  мост docker.

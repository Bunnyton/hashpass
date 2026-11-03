---
tags: docker, compose, healthcheck, перезапуск, надёжность
---
# Compose: порядок запуска, здоровье, перезапуск

Сервисы проекта зависят друг от друга: сайту нужна база, очереди — сеть. А compose запускает
их почти одновременно — кто успел, тот успел. Здесь — как найти, кто упал и почему, как
заставить compose ждать готовности соседа и как поднимать упавшее без дежурного.

## Кто упал и что сказал

    docker compose ps -a              статусы всех, включая упавших
    docker compose logs               журналы всех сервисов вперемешку
    docker compose logs web           журнал одного сервиса
    docker compose logs -f --tail 20  последние 20 строк и следить дальше

Пример: `books` готовится шесть секунд, а `reader` проверяет его один раз при старте. Здесь и
дальше `ps` сокращён до двух колонок ключом `--format 'table {{.Service}}\t{{.Status}}'`.

    $ docker compose ps -a
    SERVICE   STATUS
    books     Up 2 seconds
    reader    Exited (1) 2 seconds ago
    $ docker compose logs
    reader-1  | wget: can't connect to remote host (192.168.16.2): Connection refused
    reader-1  | reader - каталог не отвечает
    books-1   | books - читаю каталог

## depends_on: порядок запуска

    services:
      reader:
        depends_on:
          - books

Короткая запись даёт только **порядок**: compose запустит `books` раньше `reader`. И всё. В
примере выше `depends_on` был — и не помог: контейнер `books` запустился, но отвечать ещё не
мог. «Запущен» — не значит «готов».

## healthcheck: проверка здоровья

Чтобы compose знал, готов ли сервис, у сервиса описывают **healthcheck**:

1. Это команда, которую docker сам запускает **внутри** контейнера раз в `interval`.
2. Код выхода 0 — здоров, не 0 — неудача.
3. `retries` неудач подряд — статус `unhealthy`.

    services:
      books:
        healthcheck:
          test: ["CMD-SHELL", "test -f /www/index.html"]
          interval: 2s        # как часто проверять
          retries: 10         # сколько неудач подряд — и unhealthy
          start_period: 30s   # (необязательно) поблажка на медленный старт

`test` пишут списком: `["CMD", "программа", "аргумент", …]` — запуск напрямую,
`["CMD-SHELL", "строка"]` — через `sh -c`. Проверка зависит от сервиса:

| Сервис | Обычная проверка |
|---|---|
| PostgreSQL | `pg_isready -U postgres` |
| redis | `redis-cli ping` |
| MySQL | `mysqladmin ping` |
| всё, что отвечает по HTTP | `wget -qO- http://localhost/…` или `curl -f …` |

Программа проверки должна быть **в образе сервиса**: в `alpine` нет `curl`, в `busybox` нет
`pg_isready`. Нет программы — проверка всегда падает, и сервис навсегда `unhealthy`.

Статус здоровья виден прямо в `ps`:

    $ docker compose ps
    SERVICE   STATUS
    books     Up 3 seconds (health: starting)
    reader    Created
    …
    books     Up 8 seconds (healthy)
    reader    Up 1 second

А история последних проверок — в `docker inspect` (поле `State.Health.Log`: время, код,
вывод). Туда смотрят, когда сервис застрял в `unhealthy`.

## Ждать здоровья, а не запуска

Длинная запись `depends_on` умеет условие:

    depends_on:
      books:
        condition: service_healthy

| condition | compose ждёт, пока сервис… |
|---|---|
| `service_started` | запустится (так работает короткая запись) |
| `service_healthy` | пройдёт healthcheck |
| `service_completed_successfully` | завершится с кодом 0 — для разовых задач вроде миграций |

С ним `up` сам ждёт:

    $ docker compose up -d
     …
     Container my-test-library-books-1 Waiting
     Container my-test-library-books-1 Healthy
     Container my-test-library-reader-1 Started

## Политика перезапуска

Что docker сделает, когда контейнер завершится, решает `restart:` у сервиса (у `docker run` —
`--restart`):

    no               ничего — по умолчанию
    on-failure       поднять снова, если код не 0; on-failure:5 — не больше пяти попыток
    unless-stopped   поднимать всегда, кроме случая, когда остановили вручную
    always           поднимать всегда — даже остановленный вручную, после перезапуска docker

С `on-failure` сервис, упавший с кодом 2, через секунду снова работает, а счётчик перезапусков
вырос:

    $ docker compose ps
    SERVICE   STATUS
    books     Up 11 seconds (healthy)
    reader    Up 1 second
    $ docker inspect -f '{{.RestartCount}}' my-test-library-reader-1
    1

Ручная остановка — `docker stop` или `docker compose stop` — политику не будит. Если сервис
падает снова и снова, в `ps` видно `Restarting (2) …` — значит, причину надо искать в журнале,
перезапуск её не лечит.

Поменял `compose.yaml` — не забудь `docker compose up -d`: политика и проверка здоровья
записываются в контейнер при создании, и compose пересоздаст изменившийся сервис.

## Источники

- [Control startup order](https://docs.docker.com/compose/how-tos/startup-order/) —
  `depends_on` и `condition`.
- [Справочник services](https://docs.docker.com/reference/compose-file/services/) — поля
  `healthcheck`, `depends_on`, `restart`.
- [HEALTHCHECK в Dockerfile](https://docs.docker.com/reference/dockerfile/) — та же проверка,
  зашитая в образ.
- [Start containers automatically](https://docs.docker.com/engine/containers/start-containers-automatically/)
  — политики перезапуска.
- [docker compose logs/ps](https://docs.docker.com/reference/cli/docker/compose/ps/)

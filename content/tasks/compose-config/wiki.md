---
tags: docker, compose, env, сборка, секреты
---
# Compose: свой образ, .env и env_file

Готовые образы compose берёт из реестра. Но свой сервис — это свой образ: в реестре его нет,
есть только `Dockerfile` рядом. И настройки у него меняются от сервера к серверу: порт,
заголовок, пароли. Здесь — как compose собирает образ сам и как держать настройки вне
`compose.yaml`.

## image: — скачать готовый

`image:` говорит «возьми готовый образ с таким именем». Если на машине его нет, compose идёт в
реестр — и для своего образа получает отказ:

    $ docker compose up -d
     Image my-test-notes Pulling
     Image my-test-notes Error pull access denied for my-test-notes, repository does not exist or may require 'docker login' …

## build: — собрать самому

`build:` говорит «собери из каталога с Dockerfile». Путь — от каталога, где лежит
`compose.yaml`:

    services:
      api:
        build: ./api          # здесь лежит Dockerfile

При первом `up` compose соберёт образ и запустит контейнер — как `docker build` и `docker run`
одной командой. Имя образа по умолчанию — `проект-сервис`. Если указать и `image:`, оно станет
именем собранного образа:

    services:
      notes:
        build: .
        image: my-test-notes:dev

Тонкость: образ, который уже есть, compose второй раз не собирает. Поменял Dockerfile или
файлы рядом — пересобери явно:

    docker compose up -d --build      пересобрать и пересоздать
    docker compose build              только собрать

## Подстановка `${…}` и файл .env

Значения, которые меняются от сервера к серверу, пишут в `compose.yaml` как `${ИМЯ}`, а сами
значения держат в файле **`.env`** рядом — по строке `ИМЯ=значение`, с пробелами — в кавычках:

    # .env
    SITE_NAME="Мои заметки"
    NOTES_PORT=8462

    # compose.yaml
    services:
      notes:
        build: .
        environment:
          SITE_NAME: "${SITE_NAME:-Заметки}"
        ports:
          - "${NOTES_PORT}:80"

Подставляет compose при чтении файла — как оболочка: ищет переменную в окружении, потом в
`.env`. Что получилось, показывает `docker compose config`:

    $ docker compose config
    name: my-test-notes
    services:
      notes:
        …
        environment:
          SITE_NAME: Мои заметки
        ports:
          - mode: ingress
            target: 80
            published: "8462"
            protocol: tcp

Без `.env` переменной нет, и compose честно предупредит — а подставит пустоту:

    time="2026-11-04T02:23:09+03:00" level=warning msg="The \"NOTES_PORT\" variable is not set. Defaulting to a blank string."

Запасные варианты прямо в записи:

| Запись | Значит |
|---|---|
| `${X}` | значение X; нет — пусто и предупреждение |
| `${X:-по умолчанию}` | нет X — взять «по умолчанию» |
| `${X:?текст}` | нет X — остановиться с ошибкой «текст» |

    $ docker compose config        # с ${NOTES_PORT:?задай NOTES_PORT в .env} и без .env
    error while interpolating services.notes.ports.[]: required variable NOTES_PORT is missing a value: задай NOTES_PORT в .env

Так один `compose.yaml` годится и для ноутбука, и для боевого сервера: у каждого свой `.env`.
`.env` в git не кладут — кладут пример `.env.example` с пустыми значениями.

## env_file — весь файл в контейнер

`.env` подставляет значения **в сам `compose.yaml`**. Задача бывает другой: передать
контейнеру переменные из файла, не называя ни одной в `compose.yaml`. Для этого у сервиса есть
`env_file` — то же, что `--env-file` у `docker run`:

    services:
      api:
        env_file: api.env

Каждая строка `ИМЯ=значение` файла станет переменной окружения контейнера. Проверить, что
видит сам сервис:

    $ docker compose exec notes env
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    HOSTNAME=b9d3d2b0568d
    SITE_NAME=Мои заметки
    API_TOKEN=s3cr3t-42
    API_URL=https://api.example.org
    HOME=/root

Так держат секреты: `compose.yaml` — в git, файл с паролями — только на сервере.

Грабли: `docker compose config` показывает переменные из `env_file` открытым текстом, вместе с
паролями. Его вывод не вставляют в чаты и тикеты.

## Не путать

| | `.env` | `env_file:` | `environment:` |
|---|---|---|---|
| для кого | для compose.yaml (`${…}`) | для контейнера | для контейнера |
| имя файла | только `.env` (или `--env-file`) | любое | — |
| где значения | в файле | в файле | в compose.yaml |

Переменная может прийти из нескольких мест сразу — порядок старшинства описан в документации
(ссылка ниже).

## Источники

- [Compose Build Specification](https://docs.docker.com/reference/compose-file/build/) — всё
  про `build:`.
- [Interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
  — `${…}`, `.env`, значения по умолчанию.
- [Set environment variables](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
  — `environment` и `env_file`.
- [Precedence](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)
  — кто главнее, если переменная задана в нескольких местах.
- [Twelve-Factor App: конфигурация](https://12factor.net/ru/config) — почему настройки держат
  в окружении, по-русски.

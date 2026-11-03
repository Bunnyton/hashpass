---
tags: docker, реестр, образы, доставка
---
# Реестр образов: tag, push, pull

Образ мало собрать — его нужно доставить туда, где он будет работать. Копировать файлы руками
не нужно: образы хранят на **реестре** (registry) — сервере образов. Самый известный — Docker
Hub, оттуда приходят `alpine`, `redis`, `nginx`. Но реестр можно поднять и свой.

## Как образ ходит через реестр

1. Собрал образ у себя (`docker build`).
2. `docker push <образ>` — отправил его в реестр.
3. На сервере `docker pull <образ>` — скачал. `docker run` делает pull сам, если образа на
   машине нет.

## Куда — написано в имени

Отдельного ключа «куда отправить» у `docker push` нет. Адрес реестра — часть **имени**
образа:

    registry.example.com:5000 / team/app : 2.1
    └─ адрес реестра ───────┘  └ имя ──┘  └ метка

- нет адреса — это Docker Hub (`docker.io`), а имя без `/` — его раздел `library/`;
- нет метки — это `latest`.

Поэтому образ с «домашним» именем docker честно повезёт на Docker Hub — и получит отказ:

    $ docker push my-test-tool:1
    The push refers to repository [docker.io/library/my-test-tool]
    97e4ece8f8a4: Preparing
    denied: requested access to the resource is denied

Та же логика при запуске: несуществующий образ docker ищет на Docker Hub.

    $ docker run --rm my-test-nothing:1
    Unable to find image 'my-test-nothing:1' locally
    docker: Error response from daemon: pull access denied for my-test-nothing, repository does not exist …

## Свой реестр — это тоже контейнер

Официальный образ реестра — `registry:2`. Внутри он слушает порт 5000, работает как сервер —
значит, в фоне и с проброшенным портом. Здесь он проброшен на порт 5050 машины:

    $ docker run -d --name my-test-reg -p 5050:5000 registry:2
    $ curl -s http://localhost:5050/v2/_catalog
    {"repositories":[]}

У реестра HTTP-интерфейс: `/v2/_catalog` — какие образы есть, `/v2/<имя>/tags/list` — какие у
образа метки.

## Новое имя — `docker tag`

`docker tag` даёт существующему образу ещё одно имя. Образ не копируется — у того же ID
появляется ещё одна строка в списке:

    $ docker tag busybox:1.36 localhost:5050/tools/busybox:1.36
    $ docker images --format '{{.Repository}}:{{.Tag}}  {{.ID}}' | grep busybox
    busybox:1.36  b116e1550744
    busybox:latest  b116e1550744
    localhost:5050/tools/busybox:1.36  b116e1550744

## Отправить и проверить

    $ docker push localhost:5050/tools/busybox:1.36
    The push refers to repository [localhost:5050/tools/busybox]
    97e4ece8f8a4: Preparing
    97e4ece8f8a4: Pushed
    1.36: digest: sha256:5b0745afdfec8efe7225bbe20cd87dc9139381e676400707ea979ec5406de3a8 size: 527
    $ curl -s http://localhost:5050/v2/_catalog
    {"repositories":["tools/busybox"]}
    $ curl -s http://localhost:5050/v2/tools/busybox/tags/list
    {"name":"tools/busybox","tags":["1.36"]}

**digest** — отпечаток содержимого (sha256). Метку можно перевесить на другой образ, digest —
нет: `образ@sha256:…` всегда означает ровно эти байты.

## Удалить у себя — скачать обратно

`docker rmi` снимает с образа одно имя; сам образ исчезает, когда снято последнее:

    $ docker rmi localhost:5050/tools/busybox:1.36
    Untagged: localhost:5050/tools/busybox:1.36
    Untagged: localhost:5050/tools/busybox@sha256:5b0745afdfec…

Образ, на котором есть контейнер (хоть остановленный), docker без `-f` не удалит — сначала
убирают контейнер. Теперь запуск сам скачает образ из своего реестра:

    $ docker run --rm localhost:5050/tools/busybox:1.36 echo из реестра
    Unable to find image 'localhost:5050/tools/busybox:1.36' locally
    1.36: Pulling from tools/busybox
    Digest: sha256:5b0745afdfec8efe7225bbe20cd87dc9139381e676400707ea979ec5406de3a8
    Status: Downloaded newer image for localhost:5050/tools/busybox:1.36
    из реестра

## HTTPS и пароль

- По `localhost` docker ходит в реестр по простому HTTP. Любой другой адрес — только HTTPS с
  сертификатом (или явное разрешение `insecure-registries` в настройках демона — для тестов).
- Закрытые реестры просят войти: `docker login registry.example.com`.
- Данные `registry:2` держит в `/var/lib/registry` — на настоящем сервере туда подключают том.

## Где пригодится

- выкатка: сборка отправляет образ в реестр, серверы делают `docker pull` — версия в метке;
- откат: вернуться к `app:1.4` — просто запустить старую метку, она лежит в реестре;
- реестры на каждом шагу: GitLab Container Registry, GitHub (ghcr.io), Harbor, Yandex
  Container Registry — все говорят на том же протоколе `/v2/`.

## Источники

- [What is a registry? — Docker](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-registry/)
- [docker image tag](https://docs.docker.com/reference/cli/docker/image/tag/) и
  [docker image push](https://docs.docker.com/reference/cli/docker/image/push/) — имена,
  метки, отправка.
- [CNCF Distribution](https://distribution.github.io/distribution/) — документация реестра,
  который живёт в образе `registry:2`: настройка, хранилище, HTTP API.
- [registry на Docker Hub](https://hub.docker.com/_/registry) — как запускать официальный образ.
- [Изучаем Docker, часть 2: термины и концепции](https://habr.com/ru/companies/ruvds/articles/439978/)
  — реестры, репозитории, метки по-русски.

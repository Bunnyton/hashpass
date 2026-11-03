---
tags: docker, отладка, логи, env
---
# Контейнер упал: логи, переменные, файлы изнутри

Сервис запустили — а он не работает. Гадать не надо: docker помнит, что с контейнером было и
что он успел сказать. Разбираются по шагам — от «что с ним» к «почему» и «как починить».

## 1. Что с контейнером

`docker ps` показывает только работающие. Упавшие — с ключом `-a`:

    $ docker ps -a --filter name=my-test-mailer --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
    NAMES            IMAGE     STATUS
    my-test-mailer   alpine    Exited (1) 1 second ago

`Exited (N)` — программа завершилась, `N` — её код выхода. Как читать код:

| Код | Что обычно значит |
|---|---|
| 0 | закончила работу и вышла сама — всё хорошо |
| 1, 2, … | программа сама сообщила об ошибке |
| 126 | команда есть, но её нельзя запустить (нет прав) |
| 127 | команда не найдена |
| 137 | убита сигналом 9 (128 + 9) — часто нехватка памяти |
| 143 | остановлена сигналом 15 (128 + 15) — обычный `docker stop` |

То же числом — из `docker inspect`:

    $ docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' my-test-mailer
    exited 1

## 2. Что он успел сказать

Всё, что программа печатает (и в stdout, и в stderr), docker сохраняет — даже у контейнера в
фоне и даже у упавшего:

    $ docker logs my-test-mailer
    mailer: старт
    mailer: не задана переменная SMTP_HOST

Полезные ключи:

    docker logs --tail 20 web      только последние 20 строк
    docker logs -f web             следить за журналом вживую (выход — Ctrl+C)
    docker logs --since 10m web    за последние 10 минут
    docker logs -t web             с отметкой времени у каждой строки

Журнал живёт, пока жив контейнер: `docker rm` — и он пропал. Поэтому упавший контейнер сначала
читают, потом удаляют.

## 3. Настройки снаружи — переменные окружения

Образ один на все серверы, а адреса базы, почты, ключи API — на каждом свои. Их не зашивают в
образ, а передают при запуске **переменными окружения**: пары `ИМЯ=значение`, которые
программа читает при старте.

По одной — ключом `-e` (сколько угодно раз). Файл, где каждая строка — `ИМЯ=значение`, —
ключом `--env-file`:

    $ cat mail.env
    SMTP_HOST=mail.example.org
    SMTP_PORT=587
    $ docker run -d --name my-test-mailer --env-file mail.env -e LANG=C.UTF-8 alpine sh -c '…'
    $ docker logs my-test-mailer
    mailer: старт
    почта — mail.example.org

Что дошло до контейнера на самом деле:

    $ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' my-test-mailer
    SMTP_HOST=mail.example.org
    SMTP_PORT=587
    LANG=C.UTF-8
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

Грабли:

- **Переменные задаются только при создании.** У готового контейнера их не поменять — его
  удаляют и создают заново. Старое имя занято, пока жив старый контейнер:

        docker: Error response from daemon: Conflict. The container name "/my-test-mailer" is already in use …

- **Ключи — до имени образа.** Всё после образа — команда для контейнера. Перепутал порядок —
  docker либо примет `B=2` за имя образа, либо попытается запустить `-e` как программу:

        $ docker run --rm -e A=1 B=2 alpine env
        docker: invalid reference format: repository name (library/B=2) must be lowercase
        $ docker run --rm alpine -e A=1 env
        … exec: "-e": executable file not found in $PATH

- Значение с пробелами — в кавычки: `-e "GREETING=добрый день"`.
- `-e X` без значения берёт `X` из твоей оболочки: `X=777 docker run --rm -e X alpine …`.

## 4. Заглянуть внутрь

Файл, который сервис пишет внутри контейнера, на машине не виден. Достать его можно двумя
путями.

`docker exec` выполняет команду в **работающем** контейнере, а её вывод приходит к тебе в
терминал — с ним можно делать всё то же, что с выводом любой команды:

    $ docker exec my-test-mailer ls /out
    sent.log
    $ docker exec -it my-test-mailer sh       # оболочка внутри, выход — exit

У остановленного `exec` не сработает:

    Error response from daemon: container 3972b1239a6b… is not running

`docker cp` копирует файлы между контейнером и машиной в обе стороны — и у работающего, и у
остановленного контейнера:

    docker cp web:/etc/nginx/nginx.conf .      из контейнера на машину
    docker cp site.conf web:/etc/nginx/conf.d/ с машины в контейнер

## Где пригодится

- сервис «не поднимается» — `docker ps -a`, потом `docker logs`: девять из десяти причин там;
- проверить, с какими настройками контейнер запущен, — `docker inspect` (переменные, порты,
  тома, сколько раз перезапускался);
- вытащить отчёт, дамп или конфиг из контейнера, не останавливая его.

## Источники

- [docker container logs](https://docs.docker.com/reference/cli/docker/container/logs/) — все
  ключи журнала.
- [docker container exec](https://docs.docker.com/reference/cli/docker/container/exec/) и
  [docker container cp](https://docs.docker.com/reference/cli/docker/container/cp/).
- [docker container inspect](https://docs.docker.com/reference/cli/docker/container/inspect/)
  — что можно узнать о контейнере и как достать одно поле через `-f`.
- [Twelve-Factor App: конфигурация](https://12factor.net/ru/config) — почему настройки держат в
  переменных окружения, а не в коде.
- [Изучаем Docker, часть 5: команды](https://habr.com/ru/companies/ruvds/articles/440660/) —
  по-русски, на Хабре.

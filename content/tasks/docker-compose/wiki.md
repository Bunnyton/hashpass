---
tags: docker, compose, yaml, сервисы
---
# Docker Compose: весь проект в одном файле

Настоящий проект — это несколько контейнеров: сайт, база, кэш. Запускать каждый своей
командой `docker run` с длинным хвостом ключей — значит однажды забыть сеть или перепутать
порт. **Docker Compose** описывает все контейнеры проекта в одном файле, а поднимает и убирает
их одной командой.

## compose.yaml

Файл называется `compose.yaml` (старые имена `docker-compose.yml` тоже понимаются) и лежит в
каталоге проекта:

    services:
      menu:
        image: busybox:1.36
        command: httpd -f -p 80 -h /www
      web:
        image: nginx:alpine
        ports:
          - "8461:80"

- `services:` — список контейнеров; каждый здесь называется **сервисом**;
- под ним с отступом — имя сервиса и двоеточие;
- ещё глубже — настройки. Это те же ключи `docker run`, только записанные полями:

| `docker run` | compose.yaml |
|---|---|
| образ в конце команды | `image: nginx:alpine` |
| команда после образа | `command: …` |
| `-p 8461:80` | `ports:` / `- "8461:80"` |
| `-e KEY=value` | `environment:` / `KEY: value` |
| `-v ./site:/www` | `volumes:` / `- ./site:/www` |
| `--name` | не нужно: имя даёт compose |

## YAML: два правила

1. Вложенность — отступами из **пробелов**. Табы запрещены, у соседних полей отступ одинаковый.
2. Элемент списка — строка с `- `. Порты берут в кавычки: `"8461:80"`.

Сломанный отступ compose не простит:

    $ docker compose config      # табуляция вместо пробелов
    go-yaml load error in scanner (while scanning for the next token) at L3.C1: found character that cannot start any token
    $ docker compose config      # у ports на пробел меньше, чем у image
    go-yaml load error in parser (while parsing a block mapping) at L2.C3-L4.C4: did not find expected key

`docker compose config` — проверка без запуска: читает файл и печатает, как его понял.

## Поднять, посмотреть, прочитать журнал

Команды compose ищут `compose.yaml` в **текущем** каталоге:

    $ cd /tmp
    $ docker compose ps
    no configuration file provided: not found

Из каталога проекта (здесь он называется `my-test-cafe`):

    $ docker compose up -d
     Network my-test-cafe_default Created
     Container my-test-cafe-web-1 Created
     Container my-test-cafe-menu-1 Created
     Container my-test-cafe-menu-1 Started
     Container my-test-cafe-web-1 Started

`-d`, как у `docker run`, уводит сервисы в фон; без него compose остаётся в консоли и печатает
их журналы, пока они работают. Имена контейнеров — `проект-сервис-номер`, проект — по имени
каталога (или ключом `-p`).

    $ docker compose ps -a
    NAME                  IMAGE          … SERVICE   STATUS                    PORTS
    my-test-cafe-menu-1   busybox:1.36   … menu      Exited (1) 1 second ago
    my-test-cafe-web-1    nginx:alpine   … web       Up 1 second               0.0.0.0:8461->80/tcp
    $ docker compose logs menu
    menu-1  | httpd: can't change directory to '/www': No such file or directory

`menu` упал: каталога `/www` в контейнере нет. Его надо подключить.

## Каталоги — `volumes`

Поле `volumes` — на том же уровне, что `image`; под ним список `- откуда:куда`, как у `-v`.
Путь на машине можно писать от каталога, где лежит `compose.yaml`: `./menu`.

Правишь файл и снова `docker compose up -d` — compose сравнит описание с тем, что работает, и
пересоздаст только изменившееся:

    $ docker compose up -d
     Container my-test-cafe-web-1 Running
     Container my-test-cafe-menu-1 Recreate
     Container my-test-cafe-menu-1 Recreated
     Container my-test-cafe-menu-1 Started

## Сеть — сама, по именам сервисов

Compose создаёт проекту сеть `проект_default` и подключает к ней всех. Внутри неё сервис
доступен соседям по **имени сервиса** — встроенный DNS, как в своей сети docker:

    $ docker compose exec web wget -qO- http://menu/
    борщ — 300 ₽

`docker compose exec <сервис> <команда>` — как `docker exec`, только по имени сервиса.

## Убрать всё

    $ docker compose down
     Container my-test-cafe-web-1 Removed
     Container my-test-cafe-menu-1 Removed
     Network my-test-cafe_default Removed

`down` удаляет контейнеры и сеть проекта. Каталоги на машине и именованные тома остаются;
тома проекта удалит `down -v`. А `stop` только останавливает — `start` поднимет те же
контейнеры.

## Шпаргалка

    docker compose up -d           поднять / применить правки
    docker compose ps [-a]         что работает (и что упало)
    docker compose logs [-f] [svc] журналы
    docker compose exec svc cmd    команда в сервисе
    docker compose config          как compose понял файл
    docker compose ls              все проекты на машине
    docker compose down [-v]       убрать (с томами)

## Источники

- [Docker Compose — обзор](https://docs.docker.com/compose/) — официальная документация.
- [Справочник compose.yaml: services](https://docs.docker.com/reference/compose-file/services/)
  — все поля сервиса.
- [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/) — сеть
  по умолчанию и имена сервисов.
- [Руководство по Docker Compose для начинающих](https://habr.com/ru/companies/ruvds/articles/450312/)
  — по-русски, на Хабре.
- [YAML за Y минут](https://learnxinyminutes.com/ru/yaml/) — синтаксис YAML на одной странице.

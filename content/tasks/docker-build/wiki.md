---
tags: docker, dockerfile, образы, сборка
---
# Свой образ: Dockerfile и docker build

Готовые образы — `nginx`, `postgres`, `python` — кто-то когда-то собрал. Свою программу ты
упаковываешь так же: кладёшь в образ её саму и всё, что ей нужно. Такой образ запустится
одинаково у тебя, у коллеги и на сервере — ради этого всё и затевалось.

Все инструкции коротко — на странице [шпаргалка по Dockerfile](wiki/dockerfile.md).

## Dockerfile — рецепт образа

Образ собирают по рецепту — текстовому файлу `Dockerfile`. Каждая строка — инструкция, они
выполняются сверху вниз. Маленький пример: образ, который мяукает.

    $ cat Dockerfile
    FROM busybox
    COPY meow.sh /meow.sh
    CMD ["sh", "/meow.sh"]

    $ cat meow.sh
    #!/bin/sh
    who="кот"
    echo "Мяу, $who!"

- **FROM** — основа. Систему с нуля никто не собирает: берут готовый образ и добавляют своё.
- **COPY** — файлы с машины внутрь образа.
- **RUN** — команда, которая выполнится **во время сборки**; её результат останется в образе
  (например, `RUN apt-get install -y curl`).
- **CMD** — что делает контейнер, когда его запускают просто по имени образа.

Рецепт — обычный текст, поэтому его хранят в git рядом с кодом: кто склонировал проект, тот
соберёт ровно такой же образ.

## docker build

    docker build -t имя каталог

`-t` (tag) — имя нового образа, строчными буквами. Последний аргумент — **контекст сборки**:
каталог, где лежит `Dockerfile` и откуда COPY берёт файлы. Часто это `.` — текущий каталог.

    $ docker build -t mytest-meow .
    ...
    #4 [1/2] FROM docker.io/library/busybox:latest
    #4 CACHED

    #6 [2/2] COPY meow.sh /meow.sh
    #6 DONE 0.1s

    #7 exporting to image
    #7 writing image sha256:9e30f758efb30bf51c0637baf3c34111b2ec5e90a6bfb432ed9740b4549bbf86 done
    #7 naming to docker.io/library/mytest-meow done

`[1/2]`, `[2/2]` — шаги рецепта по порядку. Готовый образ появился в `docker images` и
запускается, как любой другой:

    $ docker run --rm mytest-meow
    Мяу, кот!

## CMD можно подменить на один запуск

Всё, что написано после имени образа, docker выполнит **вместо** CMD:

    $ docker run --rm mytest-meow echo другое
    другое

Образ при этом не меняется — следующий `docker run mytest-meow` снова мяукнет. И команда
должна существовать внутри образа: иначе будет `executable file not found`.

## Образ — снимок

COPY положил в образ **копию** файла, какой она была в момент сборки. Контейнеры
запускаются из образа, а не из твоего каталога:

    $ sed -i 's/кот/пёс/' meow.sh
    $ docker run --rm mytest-meow
    Мяу, кот!

Поменял что-то для образа — собери его заново той же командой:

    $ docker build -t mytest-meow .
    ...
    $ docker run --rm mytest-meow
    Мяу, пёс!

Старый образ при этом не исчезает: он теряет имя и остаётся в `docker images` как `<none>`
(в новых версиях docker — `<untagged>`). Такие «висячие» образы убирает `docker image prune`.

## Если ничего не поменялось — кэш

Собери ещё раз без правок — шаги возьмутся готовыми, и сборка займёт доли секунды:

    #6 [2/2] COPY meow.sh /meow.sh
    #6 CACHED

Как устроены слои и как заставить кэш работать на себя — в
[docker-layers](/web/wiki/bunnyton/docker-layers).

## Грабли

- `requires 1 argument` — забыл последний аргумент, каталог со сборкой.
- `open Dockerfile: no such file or directory` — в этом каталоге нет `Dockerfile` (имя — с
  большой буквы).
- `repository name must be lowercase` (в старых версиях — `invalid reference format`) — в
  имени образа заглавные буквы или пробел.
- COPY видит только файлы **внутри** контекста: `COPY ../secret.txt /` упадёт с
  `"/secret.txt": not found`.

## Источники

- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) — все инструкции
  (официальная документация).
- [Writing a Dockerfile](https://docs.docker.com/get-started/docker-concepts/building-images/writing-a-dockerfile/)
  — первый Dockerfile шаг за шагом.
- [Build context](https://docs.docker.com/build/concepts/context/) — что такое контекст
  сборки и `.dockerignore`.
- [Изучаем Docker, часть 3: файлы Dockerfile](https://habr.com/ru/companies/ruvds/articles/439980/)
  — по-русски.

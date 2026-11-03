---
tags: docker, dockerfile, сборка, размер
---
# Многоступенчатая сборка: худеем образ

Чтобы **собрать** программу, нужно намного больше, чем чтобы её **запустить**: компилятор,
библиотеки для сборки, генераторы, тесты. Сайт на React собирают сотни мегабайт пакетов, а
результат — несколько файлов HTML и JavaScript. Программе на Go нужен компилятор на сотни
мегабайт, а готовый файл весит десяток.

Каждый лишний мегабайт образа кто-то скачивает: сервер при каждом обновлении, коллега,
система проверок. И каждая лишняя программа в образе — ещё одна возможная дыра.

## Сколько весит образ

Последняя колонка `docker images` — вес образа целиком, со всеми слоями. Имя после команды
сужает список:

    $ docker images mytest-fat
    IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
    mytest-fat:latest   1682d9af4339       44.4MB             0B

(В старых версиях docker колонка называется `SIZE`.) Точный размер в байтах —
`docker image inspect -f '{{.Size}}' образ`. А **из чего** вес складывается, покажет
`docker history`.

## Пример: генератор и сайт

Сайт из одной страницы, но для генерации нужны «инструменты» на 40 МБ. Первая попытка —
поставить, сгенерировать и удалить:

    FROM busybox
    COPY tools.sh make.sh /src/
    RUN sh /src/tools.sh
    RUN sh /src/make.sh
    RUN rm -rf /opt/compiler
    CMD ["httpd", "-f", "-p", "80", "-h", "/out"]

Не помогло — 44 МБ. История объясняет почему:

    $ docker history mytest-fat
    IMAGE          CREATED                  CREATED BY                                      SIZE      COMMENT
    1682d9af4339   Less than a second ago   CMD ["httpd" "-f" "-p" "80" "-h" "/out"]        0B        buildkit.dockerfile.v0
    <missing>      Less than a second ago   RUN /bin/sh -c rm -rf /opt/compiler # buildk…   0B        buildkit.dockerfile.v0
    <missing>      1 second ago             RUN /bin/sh -c sh /src/make.sh # buildkit       22B       buildkit.dockerfile.v0
    <missing>      1 second ago             RUN /bin/sh -c sh /src/tools.sh # buildkit      40MB      buildkit.dockerfile.v0

Слой с инструментами (40MB) так и лежит ниже, а `rm` добавил сверху слой в 0B, который их
просто **прячет**. Всё, что попало в образ на любом шаге, в нём и остаётся.

## Ступени

В одном Dockerfile может быть несколько `FROM`. Каждый начинает новую **ступень** (stage) —
с чистого образа, без всего, что было выше.

1. Первой ступени дают имя: `FROM образ AS имя`. Это мастерская: ставят инструменты и
   собирают результат.
2. Следующая ступень начинается со своего `FROM` и берёт из мастерской только готовое:
   `COPY --from=имя путь_там путь_здесь`.
3. Образом становится **последняя** ступень. Мастерская остаётся в кэше сборки, а в образ не
   попадает — ни инструменты, ни исходники.

Пример из документации — программа на C, компилятор нужен только в мастерской:

    FROM debian AS build
    RUN apt-get update && apt-get install -y gcc
    COPY hello.c /src/
    RUN gcc -o /src/hello /src/hello.c

    FROM debian
    COPY --from=build /src/hello /usr/local/bin/hello
    CMD ["hello"]

Тот же генератор, переписанный в две ступени (мастерская с инструментами + чистый busybox с
готовой страницей), весит как голый busybox:

    $ docker images | grep -E '^(IMAGE|mytest-(fat|slim))'
    IMAGE                                                  ID             DISK USAGE   CONTENT SIZE   EXTRA
    mytest-fat:latest                                      1682d9af4339       44.4MB             0B
    mytest-slim:latest                                     efaf300dd319       4.42MB             0B
    $ docker run --rm mytest-slim ls /opt
    ls: /opt: No such file or directory
    $ docker run --rm mytest-slim ls /out
    index.html

## Собрать только мастерскую

Ступень можно собрать отдельно — `--target` — и заглянуть внутрь, когда что-то не так:

    $ docker build --target build -t mytest-build .
    ...
    $ docker run --rm mytest-build ls /opt/compiler
    big-toolchain

Ступеней может быть сколько угодно: отдельно зависимости, отдельно тесты, отдельно сборка —
а в итог только результат.

## Грабли

- `COPY --from=` с опечаткой в имени ступени или пути — `failed to compute cache key …
  not found`. Проверь, что такой путь в мастерской правда есть.
- В итоговую ступень не попадает **ничего** из мастерской сама собой — даже `CMD` и `EXPOSE`
  пишут заново.
- Инструменты нужны там, где их запускают: генератор, запущенный в итоговой ступени, их не
  найдёт.
- Ещё худее основа: `alpine` (8 МБ), `busybox` (4 МБ), `distroless`, а для статических
  программ — вовсе `FROM scratch`.

## Источники

- [Multi-stage builds](https://docs.docker.com/build/building/multi-stage/) — официальная
  документация: имена ступеней, `--target`, `COPY --from` из чужого образа.
- [Multi-stage builds — Docker concepts](https://docs.docker.com/get-started/docker-concepts/building-images/multi-stage-builds/)
  — то же на примере с упражнением.
- [Building best practices](https://docs.docker.com/build/building/best-practices/) — выбор
  основы и прочие способы похудеть.
- [Изучаем Docker, часть 4: уменьшение размеров образов и ускорение их сборки](https://habr.com/ru/companies/ruvds/articles/440658/)
  — по-русски.

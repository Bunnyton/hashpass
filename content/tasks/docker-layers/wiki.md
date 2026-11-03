---
tags: docker, dockerfile, слои, кэш, сборка
---
# Слои образа и кэш сборки

Образ — не один большой архив, а **стопка слоёв**. Каждая инструкция Dockerfile, которая
меняет файлы (FROM, COPY, RUN), кладёт сверху новый слой, и в нём только то, что эта
инструкция изменила:

    слой 3   RUN apt-get install python3     + /usr/bin/python3 и библиотеки
    слой 2   COPY app.py /app/               + /app/app.py
    слой 1   FROM debian                     вся система Debian

## Как из слоёв получается контейнер

1. Слои образа складываются друг на друга в одну файловую систему (overlay).
2. Контейнер видит её как обычный `/` и о слоях не знает.
3. Сверху docker кладёт ещё один, тонкий слой — личный слой контейнера; всё, что программа
   меняет во время работы, пишется туда.
4. Слои образа только читаются — поэтому из одного образа можно запустить сто контейнеров.

Что контейнер успел изменить в своём верхнем слое, показывает `docker diff`:

    $ docker run -d --name mytest-w busybox sh -c 'echo hi > /hello; sleep 60'
    $ docker diff mytest-w
    A /hello

## Зачем так сложно

- **Место.** Десять образов на `debian` хранят Debian один раз: нижний слой общий.
- **Скачивание.** `docker pull` качает только слои, которых на машине ещё нет.
- **Скорость сборки.** Docker помнит, из какой инструкции и каких файлов получился слой. Если
  ничего не поменялось — слой берётся из **кэша**, в выводе это `CACHED`.

## docker history

    $ docker history mytest-cafe
    IMAGE          CREATED          CREATED BY                                      SIZE      COMMENT
    a67735a086be   1 second ago     CMD ["sh" "/app/main.sh"]                       0B        buildkit.dockerfile.v0
    <missing>      1 second ago     COPY . /app # buildkit                          320B      buildkit.dockerfile.v0
    <missing>      1 second ago     RUN /bin/sh -c sh /app/install.sh # buildkit    3MB       buildkit.dockerfile.v0
    <missing>      10 seconds ago   COPY requirements.txt install.sh /app/ # bui…   141B      buildkit.dockerfile.v0
    <missing>      3 years ago      BusyBox 1.36.1 (glibc), Debian 13               4.42MB

1. Сверху — последний слой, внизу — самый первый, из FROM.
2. `CREATED BY` — инструкция, которая сделала слой. Длинные обрезаны `…`; целиком —
   `docker history --no-trunc`.
3. `SIZE` — сколько слой добавил. `0B` — настройки вроде `CMD`: файлов они не меняют.
4. `<missing>` — не ошибка: у промежуточных слоёв просто нет своего ID образа.

## Как docker решает, брать ли слой из кэша

1. Идёт по Dockerfile сверху вниз.
2. Для каждой инструкции спрашивает: «такой слой уже был — с той же инструкцией поверх того
   же слоя?»
3. Для COPY важно ещё **содержимое** копируемых файлов: поменялся хоть один байт — слой новый.
4. Как только один слой новый, **все инструкции ниже** выполняются заново: они строились
   поверх старого.

Смотреть удобно с `--progress=plain` — сборка печатается целиком, с выводом RUN.

## Пример: кофейня, которая долго собирается

Установщик библиотек здесь спит 8 секунд — как настоящий `pip install`:

    FROM busybox
    COPY . /app
    RUN sh /app/install.sh
    CMD ["sh", "/app/main.sh"]

Дописали строчку в меню и пересобрали:

    $ time docker build --progress=plain -t mytest-cafe .
    #6 [2/3] COPY . /app
    #6 DONE 0.1s
    #7 [3/3] RUN sh /app/install.sh
    #7 0.351 ставлю coffee-lib...
    #7 DONE 8.4s

    real	0m8.975s

`COPY .` копирует весь каталог, меню в том числе. Меню поменялось — слой новый, и `RUN` под
ним выполняется снова.

## Правило: редкое — выше, частое — ниже

Установке нужны только список библиотек и сам установщик. Их кладут в образ отдельно и
раньше, ставят библиотеки, а остальное копируют после:

    FROM busybox
    COPY requirements.txt install.sh /app/
    RUN sh /app/install.sh
    COPY . /app
    CMD ["sh", "/app/main.sh"]

Ещё одна правка меню:

    #6 [2/4] COPY requirements.txt install.sh /app/
    #6 CACHED
    #7 [3/4] RUN sh /app/install.sh
    #7 CACHED
    #8 [4/4] COPY . /app
    #8 DONE 0.1s

    real	0m0.502s

Восемь секунд превратились в полсекунды. Первая сборка после перестановки ещё будет долгой —
кэша для нового порядка пока нет. Так устроены Dockerfile настоящих проектов: сначала
`requirements.txt` / `package.json` / `go.mod` и установка, потом код.

## Ещё грабли

- `RUN apt-get update` отдельной строкой закэшируется навсегда, и `install` потом пойдёт по
  старому списку пакетов. Пиши их в одном RUN: `apt-get update && apt-get install -y …`.
- `RUN rm` в конце не уменьшает образ: файлы остались в слое ниже, новый слой их лишь прячет.
  Как худеть по-настоящему — в [docker-multistage](/web/wiki/bunnyton/docker-multistage).
- Собрать начисто, без кэша: `docker build --no-cache`.

## Источники

- [Understanding the image layers](https://docs.docker.com/get-started/docker-concepts/building-images/understanding-image-layers/)
  — слои на примерах (официальная документация).
- [Using the build cache](https://docs.docker.com/get-started/docker-concepts/building-images/using-the-build-cache/)
  и [Docker build cache](https://docs.docker.com/build/cache/) — как работает и когда
  ломается кэш.
- [Building best practices](https://docs.docker.com/build/building/best-practices/) — порядок
  инструкций, `apt-get` в одном RUN и другое.
- [docker image history](https://docs.docker.com/reference/cli/docker/image/history/) — справка.
- [Изучаем Docker, часть 4: уменьшение размеров образов и ускорение их сборки](https://habr.com/ru/companies/ruvds/articles/440658/)
  — по-русски.

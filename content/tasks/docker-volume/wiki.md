---
tags: docker, тома, данные, файлы
---
# Данные снаружи контейнера: -v

Контейнер — вещь одноразовая. Обновить сервер — значит выбросить старый контейнер и запустить
новый из свежего образа. Всё, что программа записала **внутрь** контейнера, уходит вместе с
ним. А статьи блога, база данных, загруженные картинки должны жить дольше. Поэтому их держат
**снаружи** и подключают в контейнер при запуске.

## Что пишет контейнер — то с ним и умирает

Поверх файлов образа у каждого контейнера свой тонкий слой для записи. `docker diff`
показывает, что в нём появилось:

    $ docker run --name mytest-tmp busybox sh -c 'echo важное > /note.txt'
    $ docker diff mytest-tmp
    A /note.txt
    $ docker rm mytest-tmp
    mytest-tmp
    $ docker run --rm busybox cat /note.txt
    cat: can't open '/note.txt': No such file or directory

Новый контейнер из того же образа начинает с чистого листа: образ ведь не менялся.

## Каталог машины в контейнере

Ключ `-v` (volume) у `docker run`: **слева** — путь на машине, **справа** — путь внутри
контейнера, куда он ляжет. Сайт из своего каталога в nginx:

    $ docker run -d --name mytest-notes -p 18090:80 \
        -v /tmp/tmp.WE8cZHmdsx/site:/usr/share/nginx/html:ro nginx:alpine
    $ curl -s http://localhost:18090/
    <h1>Заметки</h1>

Что произошло:

1. Каталог машины **не скопирован**, а подключён (bind mount): контейнер видит те же файлы.
2. Всё, что лежало в образе по пути справа, **накрыто** — его просто не видно, пока каталог
   подключён.
3. Сервер внутри думает, что это его собственные файлы.

Поэтому правка на машине видна сразу, без перезапуска:

    $ echo '<p>новая заметка</p>' >> site/index.html
    $ curl -s http://localhost:18090/
    <h1>Заметки</h1>
    <p>новая заметка</p>

Так и работают с кодом в контейнере: правят в редакторе на машине, смотрят сразу.

## Запись в обратную сторону и :ro

Контейнер может и писать в подключённый каталог — файл окажется на машине:

    $ docker run --rm -v /tmp/tmp.WE8cZHmdsx/site:/data busybox sh -c 'echo из контейнера > /data/hello.txt'
    $ cat site/hello.txt
    из контейнера

Хозяином файла окажется пользователь из контейнера — у обычного docker это root. (В учебной
консоли docker работает без root, и файлы остаются твоими.)

Если контейнеру писать незачем, допиши `:ro` (read-only) — сервер ничего не испортит:

    $ docker exec mytest-notes sh -c 'echo x > /usr/share/nginx/html/x'
    sh: can't create /usr/share/nginx/html/x: Read-only file system

Что подключено к контейнеру, покажет `docker inspect`:

    $ docker inspect -f '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}' mytest-notes
    bind /tmp/tmp.WE8cZHmdsx/site -> /usr/share/nginx/html rw=false

## Путь или имя тома

Слева от двоеточия docker различает две вещи:

- **путь** — начинается с `/` (или `./`, `~` раскрывает bash): подключить каталог машины;
- **имя** без `/` — это **том** (named volume): хранилище, которое docker заводит и держит сам.

Перепутать легко: `-v site:/data` не подключит твой `site`, а молча создаст пустой том:

    $ docker run --rm -v site:/data busybox ls /data
    $ docker volume ls --filter name=site
    DRIVER    VOLUME NAME
    local     site

Старые версии docker на относительный путь вообще ругаются: `must be absolute`.

Тома удобны для баз данных: docker сам выбирает, где хранить, а имя запомнить проще пути.

    $ docker volume create mytest-data
    mytest-data
    $ docker run --rm -v mytest-data:/data busybox sh -c 'echo запись 1 >> /data/log.txt'
    $ docker run --rm -v mytest-data:/data busybox cat /data/log.txt
    запись 1

Два разных одноразовых контейнера — а запись на месте. Удаление контейнера тома не трогает;
убирают его отдельно — `docker volume rm`.

## Удалить контейнер, сохранить данные

Работающий контейнер `docker rm` не удаляет — сначала его останавливают, а как удалить силой,
расскажет `docker rm --help`. Подключённый каталог при этом остаётся на машине нетронутым.

## Источники

- [Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) — каталоги машины в
  контейнере, `:ro`, отличия `-v` и `--mount` (официальная документация).
- [Volumes](https://docs.docker.com/engine/storage/volumes/) — тома docker.
- [Persisting container data](https://docs.docker.com/get-started/docker-concepts/running-containers/persisting-container-data/)
  — то же попроще, с упражнением.
- [Изучаем Docker, часть 6: работа с данными](https://habr.com/ru/companies/ruvds/articles/441574/)
  — по-русски.

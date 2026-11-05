---
tags: docker, redis, тома, данные, базы
---
# База в контейнере и её данные

Базу данных можно не ставить на сервер, а запустить из образа — за секунду, со всеми
библиотеками и настройками внутри. Подвох один: контейнер одноразовый. Здесь — как с базой
говорить, куда деваются её данные и как сделать, чтобы они жили дольше контейнера.

## Имя вместо ID

Сервер в контейнере запускают в фоне (`-d`) и сразу дают ему имя (`--name`) — дальше все
команды обращаются к нему по имени, а не по длинному ID:

    $ docker run -d --name my-test-kv redis:7-alpine
    94d743d5c3f7...
    $ docker ps --filter name=my-test-kv --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}'
    CONTAINER ID   IMAGE            STATUS        NAMES
    94d743d5c3f7   redis:7-alpine   Up 1 second   my-test-kv

Имя уникально: второй контейнер с тем же именем docker не создаст, пока жив первый — даже
остановленный. Старый убирают `docker rm` (работающий — `docker rm -f`).

## redis: ключ — значение

**redis** держит пары «ключ — значение» в памяти и отвечает за доли миллисекунды. Им
пользуются для корзин, сессий, кэша, счётчиков. Говорят с ним программой `redis-cli`, а она
живёт внутри контейнера, рядом с сервером. Команду в работающем контейнере выполняет
`docker exec <контейнер> <команда>`:

    $ docker exec my-test-kv redis-cli SET city "Нижний Новгород"
    OK
    $ docker exec my-test-kv redis-cli GET city
    Нижний Новгород

Без кавычек оболочка разрежет значение на слова, и redis получит лишние аргументы:

    $ docker exec my-test-kv redis-cli SET city Нижний Новгород
    ERR syntax error

Ещё полезное:

    $ docker exec my-test-kv redis-cli SET visits 1
    OK
    $ docker exec my-test-kv redis-cli INCR visits     # +1 к числу, атомарно
    2
    $ docker exec my-test-kv redis-cli KEYS '*'        # какие ключи есть
    visits
    city
    $ docker exec my-test-kv redis-cli EXPIRE city 60  # ключ сам исчезнет через минуту
    1
    $ docker exec my-test-kv redis-cli TTL city        # сколько секунд ему осталось
    60

Поговорить с базой «вживую», строка за строкой, — `docker exec -it <контейнер> redis-cli`
(выход — `quit`). Ключ `-it` даёт терминал, без него интерактивная программа не заработает.

## Контейнер одноразовый

У каждого контейнера свой слой для записи поверх образа. Удалил контейнер — удалил и всё, что
он успел записать. Новый контейнер из того же образа начинает с чистого листа:

    $ docker run --name my-test-a alpine sh -c 'echo "первая запись" > /note.txt; cat /note.txt'
    первая запись
    $ docker rm my-test-a
    $ docker run --rm alpine cat /note.txt
    cat: can't open '/note.txt': No such file or directory

Для программы это нормально — она в образе. Для данных базы — катастрофа.

## Тома: данные отдельно от контейнера

**Том** (volume) — каталог, который docker хранит отдельно от контейнеров и подключает внутрь
ключом `-v`. Два вида:

    -v /home/me/site:/www      каталог машины (bind mount): путь выбираешь ты
    -v notes:/notes            именованный том: место выбирает docker, ты знаешь только имя

Если тома с таким именем нет, docker создаст его сам при первом запуске. Следующий контейнер с
тем же томом увидит те же файлы:

    $ docker run --rm -v my-test-notes:/notes alpine sh -c 'echo "запуск $(hostname)" >> /notes/log.txt'
    $ docker run --rm -v my-test-notes:/notes alpine sh -c 'echo "запуск $(hostname)" >> /notes/log.txt; cat /notes/log.txt'
    запуск 16a83b7a56dc
    запуск 05ab0108b67d

Два разных контейнера, один журнал. Тома живут, пока их не удалят явно:

    $ docker volume ls --filter name=my-test
    DRIVER    VOLUME NAME
    local     my-test-notes
    $ docker volume inspect my-test-notes     # где лежит на диске, когда создан
    $ docker volume rm my-test-notes

Для баз берут именованный том: не нужно думать о путях и правах на машине.

## Безымянные тома

Многие образы баз сами объявляют каталог данных томом (`VOLUME` в Dockerfile). Не дашь ему
имя — docker создаст безымянный, с длинным хешем вместо имени:

    $ docker inspect -f '{{range .Mounts}}{{.Type}} {{.Name}} {{.Destination}}{{println}}{{end}}' my-test-kv
    volume 2db34a0349f41bfa3942e8ffe92784d3a6620e13645484fdd0de13b1ba35b271 /data

Данные там лежат, но следующий контейнер их не найдёт — он получит новый безымянный том. А
старые копятся на диске: `docker rm -v` удаляет контейнер вместе с его безымянными томами,
`docker volume prune` чистит все ничейные.

## Где пригодится

- обновить базу — удалить контейнер и запустить новый образ с тем же томом;
- поднять тестовую базу на пять минут и выкинуть без следа (`--rm`, без тома);
- посмотреть, где у контейнера данные, — раздел `Mounts` в `docker inspect`.

Сами тома подробнее — в [docker-volume](/web/wiki/bunnyton/docker-volume).

## Источники

- [Volumes — документация Docker](https://docs.docker.com/engine/storage/volumes/) — тома,
  `-v` и `--mount`, жизненный цикл.
- [docker container exec](https://docs.docker.com/reference/cli/docker/container/exec/) — все
  ключи `docker exec`.
- [Команды redis](https://redis.io/docs/latest/commands/) — SET, GET, INCR, EXPIRE и сотни
  других.
- [Как redis сохраняет данные](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
  — RDB-снимки и журнал AOF.
- [Изучаем Docker, часть 6: работа с данными](https://habr.com/ru/companies/ruvds/articles/441574/)
  — тома по-русски, на Хабре.

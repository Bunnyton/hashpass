---
tags: git, хуки, ci, сервер, выкладка
---
# Выкладка по git push: серверные хуки и CI/CD

Сайт выкладывают руками: зашёл на сервер, скопировал файлы, один забыл — сайт сломан. Лучше
так: человек делает `git push`, а сервер **сам** проверяет код и выкладывает его. Это и есть
CI/CD — здесь в миниатюре, на двух серверных хуках git.

## Голый репозиторий

Репозиторий на сервере, куда все делают `push`, — **голый** (bare): в нём только история,
без рабочего каталога. То, что у тебя лежит в `.git`, у него лежит прямо в корне:

    $ git init --bare srv/blog.git
    Initialized empty Git repository in /tmp/tmp.JhZcolbuv4/srv/blog.git/
    $ ls srv/blog.git
    branches
    config
    description
    HEAD
    hooks
    info
    objects
    refs

Значит, и хуки сервера — в `hooks/` внутри него. Пушить в обычный репозиторий с рабочим
каталогом git не даст (по умолчанию): файлы у того, кто там работает, разъехались бы с
историей.

## Что происходит при push

1. Ты делаешь `git push`, коммиты летят на сервер.
2. Сервер запускает **`pre-receive`** — до приёма. Код выхода не 0 — push отклонён целиком.
3. Сервер принимает коммиты, двигает ветки.
4. Сервер запускает **`post-receive`** — push уже принят, можно что-то сделать с новым кодом.

Хуки запускаются **внутри** голого репозитория: команды git в них работают с ним без путей.
Всё, что хук печатает, отправитель увидит со словом `remote:`. Хук должен быть исполняемым —
как и на твоей машине ([хуки на клиенте](/web/wiki/bunnyton/git-hooks)).

## Выложить ветку в каталог

У голого репозитория нет файлов — только история. Разложить файлы ветки в обычный каталог
умеет `git checkout`, если назначить ему рабочий каталог на время одной команды:

    git --work-tree=/var/www/blog checkout -f main

`--work-tree` — куда класть, `main` — какую ветку, `-f` — перезаписать, что там лежит.
Удалённые из ветки файлы такой `checkout` в каталоге не удалит — для чистой выкладки каталог
иногда сначала очищают. Хук `post-receive` с такой строкой — и выкладка случается на каждый
push:

    $ git push origin main
    remote: Already on 'main'
    remote: Выложено: 02:19:59
    To /tmp/tmp.JhZcolbuv4/srv/blog.git
     * [new branch]      main -> main
    $ ls srv/www/blog
    config.json
    index.html

Строки `remote:` напечатал хук. Проверяй выкладку **делом**: правка → коммит → push → файл
на сервере поменялся? Сайт, который отдаёт веб-сервер, можно сразу открыть `curl`.

Если кто-то отправил раньше тебя, сервер не примет push (`rejected`), пока ты не заберёшь
чужие коммиты: `git pull`, потом снова `git push` ([работа с сервером](/web/wiki/bunnyton/git-remote)).

## Проверка до приёма: pre-receive

Сломанное не должно доехать до людей — значит, проверка стоит **до** приёма. `pre-receive`
читает со стандартного входа строку на каждую отправленную ветку:

    <старый-хеш> <новый-хеш> refs/heads/main

Коммиты уже на сервере, но ветки ещё не сдвинуты — смотреть на них можно, по новому хешу. Файл
из коммита достаёт `git show <хеш>:путь`. Пример — не принимать push, если `config.json` не
читается как JSON:

```sh
#!/bin/sh
# каждая строка входа: <старый> <новый> <ветка>
while read old new ref; do
    if ! git show "$new:config.json" | python3 -m json.tool >/dev/null 2>&1; then
        echo "config.json в $ref не читается как JSON — не принимаю" >&2
        exit 1
    fi
done
```

    $ git push
    remote: config.json в refs/heads/main не читается как JSON — не принимаю
    To /tmp/tmp.JhZcolbuv4/srv/blog.git
     ! [remote rejected] main -> main (pre-receive hook declined)
    error: failed to push some refs to '/tmp/tmp.JhZcolbuv4/srv/blog.git'

`post-receive` после отказа даже не запускается — сломанное не выложено. Исправил,
закоммитил, отправил — прошло:

    $ git push
    remote: Already on 'main'
    remote: Выложено: 02:19:59
    To /tmp/tmp.JhZcolbuv4/srv/blog.git
       82b0b78..d2b9d2f  main -> main

Отличие от клиентского `pre-commit`: его можно обойти `--no-verify` или просто не поставить, а
серверный хук не обойти никому.

## CI/CD

- **CI** (continuous integration) — каждое изменение сразу проверяется: собирается ли,
  проходят ли тесты.
- **CD** (continuous delivery/deployment) — проверенное само уезжает на сервер.

В GitHub Actions и GitLab CI то же самое описывают файлом в репозитории —
`.github/workflows/*.yml` или `.gitlab-ci.yml`:

```yaml
on: [push, pull_request]        # когда запускать
jobs:
  test:                         # задача — на отдельной чистой машине
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./run-tests.sh     # не 0 — красный крестик, выкладки нет
```

Идея та же, что в твоих хуках: триггер, проверка, выкладка только после успеха. Только
проверки — целые наборы тестов, а запускают их отдельные машины.

## Источники

- [githooks](https://git-scm.com/docs/githooks) — официальное описание `pre-receive`,
  `post-receive`, `update`: что получают на вход.
- [Pro Git: Установка Git на сервер](https://git-scm.com/book/ru/v2/Git-на-сервере-Установка-Git-на-сервер) —
  голые репозитории, на русском.
- [Pro Git: Хуки в Git](https://git-scm.com/book/ru/v2/Настройка-Git-Хуки-в-Git) — серверные
  хуки в той же главе.
- [Документация GitHub Actions](https://docs.github.com/ru/actions) и
  [GitLab CI/CD](https://docs.gitlab.com/ci/) — CI/CD «по-взрослому».

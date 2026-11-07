---
tags: git, remote, pull, unrelated histories, слияние
---
# refusing to merge unrelated histories

Классика первого дня: проект начат у себя (`git init`), а репозиторий на сервере создан через
веб-интерфейс GitHub или GitLab с галочками «добавить README» и «добавить лицензию». Там уже
есть свой первый коммит.

    $ git remote add origin /srv/git/blog.git
    $ git push -u origin main
     ! [rejected]        main -> main (fetch first)
    $ git pull origin main
     * [new branch]      main       -> origin/main
    fatal: refusing to merge unrelated histories

## Почему отказ

У двух историй нет общего коммита. С git 2.9 слияние таких историй по умолчанию
запрещено: чаще всего это ошибка — не тот репозиторий или не тот адрес.

## Как соединить

Убедись, что адрес верный, и разреши слияние явно:

    $ git pull --allow-unrelated-histories origin main
    Auto-merging README.md
    CONFLICT (add/add): Merge conflict in README.md
    Automatic merge failed; fix conflicts and then commit the result.

Файл, который есть в обеих историях, — конфликт `add/add`. Разбираешь как обычный: открыть,
оставить нужное, `git add`, `git commit`. Потом:

    git push -u origin main

## Как не попадать

- Создавать репозиторий на сервере **пустым**, без README, `.gitignore` и лицензии, если код
  уже есть у тебя. Тогда `git push -u origin main` проходит сразу.
- Или наоборот: сначала `git clone` пустого с сервера, потом переносить в него файлы.

## Источники

- [git merge: --allow-unrelated-histories](https://git-scm.com/docs/git-merge#Documentation/git-merge.txt---allow-unrelated-histories) —
  официальная документация.
- [Pro Git: Работа с удалёнными репозиториями](https://git-scm.com/book/ru/v2/Основы-Git-Работа-с-удалёнными-репозиториями) —
  `git remote add`, `git push -u`.
- [GitHub Docs: Adding locally hosted code to GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) —
  совет создавать репозиторий без README, если код уже есть.

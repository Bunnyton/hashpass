---
tags: git, секреты, пароль, rebase, история, gitignore
---
# Пароль попал в коммит

Закоммитил файл с паролем или токеном. Удалить его новым коммитом мало: прежние коммиты —
неизменные снимки, пароль в них остался и виден любому, кто склонирует репозиторий:

    $ git log --oneline -- secrets.txt
    3fce73f Добавил конфиг

## Пока не отправил: переписать коммит

`git rebase -i` с командой `edit` останавливается на нужном коммите:

    $ git rebase -i HEAD~2          # напротив «Добавил конфиг» — edit
    Stopped at 3fce73f...  Добавил конфиг
    $ git rm --cached secrets.txt   # из коммита — да, с диска — нет
    rm 'secrets.txt'
    $ git commit --amend --no-edit
    [detached HEAD 938b824] Добавил конфиг
     1 file changed, 1 insertion(+)
     create mode 100644 app.conf
    $ git rebase --continue
    Successfully rebased and updated refs/heads/main.

Проверка — поиск строки по всей истории ничего не находит:

    $ git log --all --oneline -S hunter2
    $

Типичные заминки по дороге:

- `untracked working tree files would be overwritten` — файл лежит на диске вне git, а rebase
  возвращает коммит, где он ещё был. Отодвинь файл и продолжи.
- `The previous cherry-pick is now empty` — коммит «удалил секрет» теперь пустой:
  `git rebase --skip`.
- Для многих коммитов и файлов есть `git filter-repo` (отдельная программа) и старый
  `git filter-branch`. Второй оставляет копию старой истории в `refs/original/` — её надо
  удалить, иначе пароль никуда не делся.

## Уже отправил: пароль скомпрометирован

Переписать историю на сервере можно (`push --force`), но копии уже могли разойтись по чужим
клонам, форкам и кэшам. Поэтому первым делом **смени пароль** — а уже потом чисти историю.

## Чтобы не повторилось

    echo .env >> .gitignore

И держи в репозитории образец без секретов — `.env.example` с пустыми значениями.

## Источники

- [Pro Git: Перезапись истории](https://git-scm.com/book/ru/v2/Инструменты-Git-Исправление-истории) —
  `rebase -i`, `edit`, разделение и удаление коммитов.
- [GitHub Docs: Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) —
  что делать, если секрет уже на сервере.
- [git-filter-repo](https://github.com/newren/git-filter-repo) — инструмент для больших чисток.

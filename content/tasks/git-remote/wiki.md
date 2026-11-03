---
tags: git, сервер, clone, push, pull
---
# Работа с сервером: clone, push, pull

Пока история лежит только у тебя, у неё две беды: умрёт диск — пропадёт всё, а коллеги не
видят твоих правок. Поэтому общий репозиторий команды держат на **сервере**: GitHub, GitLab,
Gitea или просто машина в офисе.

## Распределённость: у каждого полная копия

git распределённый. У каждого участника — **клон**: полная копия со всей историей. Коммиты,
ветки, `git log`, `git diff` — всё работает без сети. Сервер нужен только чтобы
**обмениваться** коммитами.

На сервере обычно лежит **голый** (bare) репозиторий — одна история, без рабочих файлов:
править там некому, туда только отправляют и оттуда забирают.

## Клонировать

    $ git clone /tmp/mytest-srv/notes.git anya
    Cloning into 'anya'...
    warning: You appear to have cloned an empty repository.
    done.

Адрес бывает разным, команды одни и те же:

    git clone https://github.com/user/project.git        # по HTTPS
    git clone git@github.com:user/project.git            # по SSH, с ключом
    git clone /srv/git/other.git ~/other                 # путь на этой же машине

Без второго аргумента каталог назовётся по имени репозитория (`project`). Сервер, с которого
склонировали, git запоминает под именем **origin**:

    $ git remote -v
    origin	/tmp/mytest-srv/notes.git (fetch)
    origin	/tmp/mytest-srv/notes.git (push)

## Отправить: push

Новые коммиты сначала делают у себя, как обычно, а потом отправляют:

    $ git push
    To /tmp/mytest-srv/notes.git
     * [new branch]      main -> main

На сервер уходят **коммиты** — незакоммиченные правки остаются только у тебя. Сколько
твоих коммитов ещё не отправлено, говорит `git status`:

    Your branch is ahead of 'origin/main' by 1 commit.
      (use "git push" to publish your local commits)

А `git branch -vv` покажет, с какой веткой сервера связана твоя (`[origin/main]`).

## Отказ: кто-то успел первым

Пока ты коммитил, Борис отправил свой коммит. Сервер не даст затереть его работу:

    $ git push
    To /tmp/mytest-srv/notes.git
     ! [rejected]        main -> main (fetch first)
    error: failed to push some refs to '/tmp/mytest-srv/notes.git'
    hint: Updates were rejected because the remote contains work that you do not
    hint: have locally. This is usually caused by another repository pushing to
    hint: the same ref. If you want to integrate the remote changes, use
    hint: 'git pull' before pushing again.

Это не ошибка, а нормальная жизнь команды. Читай ответ целиком — git прямо пишет, что делать.

## Забрать: fetch и pull

`git fetch` только **скачивает** новые коммиты сервера — в ветку `origin/main`, твою `main`
не трогает. Удобно сначала посмотреть, что пришло:

    $ git status
    On branch main
    Your branch and 'origin/main' have diverged,
    and have 1 and 1 different commits each, respectively.
      (use "git pull" if you want to integrate the remote branch with yours)

`git pull` = `git fetch` + `git merge`: скачать и сразу влить в текущую ветку. Вот он же
без отдельного fetch:

    $ git pull --no-edit
    From /tmp/mytest-srv/notes
       4ed3ca1..0d0b1bb  main       -> origin/main
    Merge made by the 'ort' strategy.
     todo.txt | 1 +
     1 file changed, 1 insertion(+)
    $ git push
    To /tmp/mytest-srv/notes.git
       0d0b1bb..2535b68  main -> main

Без `--no-edit` git откроет редактор для сообщения слияния — сохрани и выйди. Если правки
задели одни строки, будет [конфликт](/web/wiki/bunnyton/git-branch), разбирается так же.

    $ git log --oneline --graph --all --decorate
    *   2535b68 (HEAD -> main, origin/main) Merge branch 'main' of /tmp/mytest-srv/notes
    |\
    | * 0d0b1bb Хлеб
    * | a9287f6 Звонки
    |/
    * 4ed3ca1 Начало

## merge или rebase?

Свежий git при расходящихся ветках может отказаться от `pull` с длинным советом
`Need to specify how to reconcile divergent branches`. Он просит выбрать один раз:

    git config --global pull.rebase false   # сливать (коммит слияния, как выше)
    git config --global pull.rebase true    # переносить свои коммиты поверх чужих
    git config --global pull.ff only        # только если сливать нечего

Новичку проще `false`: ничего не переписывается.

## Не делай так

- `git push --force` «чтобы отправилось» — затрёт коммиты коллег на сервере. Если очень
  нужно, то хотя бы `--force-with-lease`.
- Работать неделю без `pull` — конфликты копятся. Забирай чужое почаще.

## Источники

- [Pro Git: Работа с удалёнными репозиториями](https://git-scm.com/book/ru/v2/Основы-Git-Работа-с-удалёнными-репозиториями) —
  remote, fetch, pull, push.
- [git clone](https://git-scm.com/docs/git-clone), [git push](https://git-scm.com/docs/git-push),
  [git pull](https://git-scm.com/docs/git-pull) — официальная документация.
- [git fetch](https://git-scm.com/docs/git-fetch) — что именно скачивается.
- [Learn Git Branching](https://learngitbranching.js.org/?locale=ru_RU) — раздел «Remote»:
  push/pull наглядно.

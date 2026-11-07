---
tags: git, detached HEAD, checkout, ветка, reflog
---
# detached HEAD

`git checkout v1.0` или `git checkout <хеш>` ставит HEAD прямо на коммит, а не на ветку:

    $ git status
    HEAD detached from v1.0

Смотреть, запускать и даже коммитить можно. Но новые коммиты не принадлежат ни одной ветке.
Уйдёшь с них — git предупредит:

    $ git switch main
    Warning: you are leaving 2 commits behind, not connected to
    any of your branches:

      c1a9139 Тест: бронь на завтра
      2567c0b Бронь: «сегодня» и «завтра» вместо даты

    If you want to keep them by creating a new branch, this may be a good time
    to do so with:

     git branch <new-branch-name> c1a9139

    Switched to branch 'main'

## Как спасти

Пока стоишь на коммитах — `git switch -c имя` (создать ветку здесь и перейти в неё).

Уже ушёл — ветку на хеш из предупреждения:

    git branch hotfix-1.0 c1a9139

Предупреждение потерялось — хеш помнит reflog:

    $ git reflog
    e84fb81 HEAD@{0}: checkout: moving from c1a9139… to main
    c1a9139 HEAD@{1}: commit: Тест: бронь на завтра

Коммиты без ветки git хранит, пока их помнит reflog (по умолчанию от двух недель до трёх
месяцев), потом сборщик мусора их удаляет.

## Как не попадать

Чинить старую версию — сразу в ветке: `git switch -c hotfix-1.0 v1.0`.

## Источники

- [git checkout: DETACHED HEAD](https://git-scm.com/docs/git-checkout#_detached_head) —
  официальная документация, с картинками.
- [Pro Git: Ветвление в двух словах](https://git-scm.com/book/ru/v2/Ветвление-в-Git-О-ветвлении-в-двух-словах) —
  что такое HEAD.

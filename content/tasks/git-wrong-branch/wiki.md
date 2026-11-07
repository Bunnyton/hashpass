---
tags: git, ветки, branch, reset, push
---
# Закоммитил не в ту ветку

Классика: увлёкся, сделал три коммита — и только потом заметил, что сидишь в `main`, а по
правилам команды новая работа идёт в отдельной ветке. Пока коммиты не отправлены, это
чинится двумя командами и ничего не теряется.

## Ветка — это метка

Коммиты не «лежат в ветке». Ветка — метка с именем, приклеенная к одному коммиту. Сделал
коммит — метка текущей ветки переехала на него. Отсюда весь приём:

1. **Повесить новую метку** на твой последний коммит: `git branch coupons`. Ничего не
   переключается, ничего не двигается — у коммита просто стало два имени.
2. **Отодвинуть метку main назад** — туда, где main стоит на сервере:
   `git reset --hard origin/main`. Коммиты остались под меткой `coupons`.

Как это выглядит в настоящем репозитории после обоих шагов:

    $ git log --oneline --all
    c854635 (coupons) Купоны: скидка в чеке
    b27bdc8 Купоны: проверка кода
    0ad1b96 Купоны: таблица кодов
    7ecc79c (HEAD -> main, origin/main, origin/HEAD) Морс подорожал
    3c0c921 Касса: сумма заказа

Порядок важен: сначала метка, потом `reset`. Наоборот — коммиты окажутся без имени, и
искать их придётся через [reflog](/web/wiki/bunnyton/git-reflog).

## origin/main — где ветка на сервере

После `clone`, `fetch` или `pull` git помнит положение веток сервера: `origin/main`. Насколько
ты ушёл вперёд, пишет `git status`:

    On branch main
    Your branch is ahead of 'origin/main' by 3 commits.
      (use "git push" to publish your local commits)

## Защищённая ветка

На GitHub и GitLab main обычно **защищена**: push в неё напрямую запрещён, изменения
попадают туда только через ревью (pull request / merge request). Сервер так и отвечает:

    remote: main защищена: сюда попадает только то, что прошло ревью. Отправь свою ветку.
     ! [remote rejected] main -> main (pre-receive hook declined)

## Отправить новую ветку

У новой ветки ещё нет пары на сервере, поэтому при первом push её называют явно:

    $ git push -u origin coupons
     * [new branch]      coupons -> coupons
    branch 'coupons' set up to track 'origin/coupons'.

`-u` запоминает пару: дальше хватит простого `git push`.

## Если коммиты уже ушли на сервер

Тогда `reset` в main не поможет — история уже у всех. Чинят новыми коммитами:
[git revert](/web/wiki/bunnyton/git-log) в main, а работу продолжают в ветке.

## Источники

- [Pro Git: О ветвлении в двух словах](https://git-scm.com/book/ru/v2/Ветвление-в-Git-О-ветвлении-в-двух-словах) —
  ветка как указатель на коммит.
- [Pro Git: Удалённые ветки](https://git-scm.com/book/ru/v2/Ветвление-в-Git-Удалённые-ветки) —
  `origin/main`, push новой ветки, `-u`.
- [git branch](https://git-scm.com/docs/git-branch), [git reset](https://git-scm.com/docs/git-reset) —
  официальная документация.
- [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) —
  что такое защищённая ветка.

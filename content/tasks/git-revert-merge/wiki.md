---
tags: git, revert, merge, слияние, откат
---
# Откатить слияние

Ветку влили в main, она сломала тест, а поверх уже есть новые коммиты, и всё это на
сервере. `reset` не годится — он переписывает общую историю. Отменяют **новым коммитом**:
`git revert`. Но у слияния есть две тонкости.

## Тонкость 1: у слияния два родителя

    $ git log --oneline --graph
    * f23389e (HEAD -> main) Сметана в меню
    * abaaf58 Курица подорожала
    *   78e8ff3 Merge branch 'promo'
    |\
    | * 9909e8b (promo) Акция: README
    | * ab56a1a Акция: касса считает скидку
    | * d6f4b35 Акция: скрипт скидки
    * | 09636ea Морс подорожал
    |/

Отменить слияние — значит вернуться к одному из родителей. git не угадывает:

    $ git revert 78e8ff3
    error: commit 78e8ff3f3f66… is a merge but no -m option was given.
    fatal: revert failed

Номер родителя — ключ `-m`. Первый родитель — ветка, **куда** вливали (main):

    $ git revert --no-edit -m 1 78e8ff3
    [main 4c0f1c7] Revert "Merge branch 'promo'"
     3 files changed, 6 deletions(-)
     delete mode 100755 promo.sh

Коммиты после слияния остались на месте.

## Тонкость 2: повторное слияние не вернёт отменённое

Ветку починили и хотят влить снова. Но слияние в истории осталось — для git старые коммиты
promo **уже влиты**. `git merge promo` несёт только новые коммиты ветки, а старые правки так
и остаются отменёнными. Если новые коммиты правят то, что убрала отмена, будет конфликт:

    $ git merge --no-edit promo
    CONFLICT (modify/delete): promo.sh deleted in HEAD and modified in promo.

Правильный порядок:

    git merge --abort          # если уже застрял
    git revert --no-edit <коммит отмены>   # отмена отмены: правки ветки вернулись
    git merge --no-edit promo  # пришло только новое — исправление

    [main 0084229] Reapply "Merge branch 'promo'"
    Merge made by the 'ort' strategy.
     promo.sh | 4 ++--

## Где пригодится

«Откатили релиз — починили — вернули» — обычная история в любой команде с общим main.
Можно и иначе: после отмены не вливать старую ветку, а сделать новую с исправленным кодом.

## Источники

- [Pro Git: Продвинутое слияние](https://git-scm.com/book/ru/v2/Инструменты-Git-Продвинутое-слияние) —
  раздел про отмену слияний и «отмену отмены».
- [git revert](https://git-scm.com/docs/git-revert) — официальная документация, ключ `-m`.
- [How to revert a faulty merge](https://git-scm.com/docs/howto/revert-a-faulty-merge) —
  разбор от авторов git: почему повторное слияние не возвращает отменённое.

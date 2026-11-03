---
tags: git, rebase, история, коммиты
---
# Причесать историю: интерактивный rebase

Пока работаешь, коммитишь как получится: «wip», «опечатка», «ещё правка». Коммит дешёвый, им
удобно сохраняться. Но в общую историю такая лесенка не нужна: через полгода никто не поймёт,
что было в «wip». Поэтому перед отправкой ветку **причёсывают** — складывают черновики в
осмысленные коммиты. Инструмент — `git rebase -i`.

## Сначала посмотри, что есть

Какие коммиты сделаны в ветке поверх `main`, показывает диапазон `main..ветка` — «есть в
ветке, нет в main»:

    $ git log --oneline main..recipe
    ed11d3c ещё правка
    8880b08 опечатка
    fee4dab wip
    23c13db борщ: черновик

Сверху — самый новый. Запомни это: в редакторе rebase будет наоборот.

## План в редакторе

`git rebase -i <база>` берёт коммиты текущей ветки после базы и открывает **план** в
редакторе — по строке на коммит, **сверху самый старый**. Под списком git сам пишет справку:

    $ git rebase -i main
    pick 23c13db борщ: черновик
    pick fee4dab wip
    pick 8880b08 опечатка
    pick ed11d3c ещё правка

    # Rebase 0b62433..ed11d3c onto 0b62433 (4 commands)
    #
    # Commands:
    # p, pick <commit> = use commit
    # r, reword <commit> = use commit, but edit the commit message
    # e, edit <commit> = use commit, but stop for amending
    # s, squash <commit> = use commit, but meld into previous commit
    # f, fixup [-C | -c] <commit> = like "squash" but keep only the previous
    #                    commit's log message, unless -C is used, in which case
    #                    keep only this commit's message; -c is same as -C but
    #                    opens the editor
    # x, exec <command> = run command (the rest of the line) using shell
    # b, break = stop here (continue rebase later with 'git rebase --continue')
    # d, drop <commit> = remove commit
    ...
    # These lines can be re-ordered; they are executed from top to bottom.
    #
    # If you remove a line here THAT COMMIT WILL BE LOST.
    #
    # However, if you remove everything, the rebase will be aborted.

По-русски самые нужные слова:

| Слово | Что будет с коммитом |
|---|---|
| `pick` | оставить как есть |
| `reword` | оставить, но переписать сообщение |
| `edit` | остановиться на нём — поправить файлы |
| `squash` | влить в **предыдущий** коммит, сообщения склеить (git спросит итоговое) |
| `fixup` | влить в предыдущий, своё сообщение выбросить |
| `drop` | выбросить коммит вместе с изменениями |

Меняешь слова, можешь переставлять строки, сохраняешь файл, выходишь — git выполняет план
сверху вниз. «Влить в предыдущий» значит: строке выше должно быть куда принимать — первая
строка плана сама никуда не вливается. Передумал до сохранения — удали все строки, rebase
отменится. Передумал посреди — `git rebase --abort`.

Редактор — тот, что настроен в `core.editor` (у тебя vim): `:wq` сохраняет и выходит.

## Проверь, что файлы не изменились

Переписывание истории не должно менять итоговых файлов. После rebase git помнит прежнюю
вершину в `ORIG_HEAD` — сравни:

    $ git diff ORIG_HEAD HEAD
    $

Пусто — значит, файлы ровно те же, поменялась только история. А `git reflog` покажет, как
шёл rebase, и вернёт всё назад, если что:

    $ git reflog -3
    160c4b1 HEAD@{0}: rebase (finish): returning to refs/heads/recipe
    160c4b1 HEAD@{1}: rebase (pick): Соль: уточнил
    23f46c2 HEAD@{2}: rebase (fixup): Щи

## Поправить последний коммит

Самый свежий коммит можно поправить без всякого rebase — `git commit --amend`. Он заменяет
последний коммит новым: с тем, что сейчас в индексе, и с новым сообщением (или прежним, если
`--no-edit`). Забыл добавить файл:

    $ git add pepper.md
    $ git commit --amend --no-edit
    [recipe d2d2dec] Соль по вкусу
     2 files changed, 2 insertions(+)

Хеш стал другим (`a5fe7d0` → `d2d2dec`) — это новый коммит. Без `--no-edit` git откроет
редактор с сообщением: там его и меняют. Сообщения более старых коммитов меняют словом
`reword` в плане.

## Приём профи: fixup-коммиты

Нашёл ошибку в коммите три шага назад — закоммить исправление с пометкой, к какому коммиту
оно относится:

    $ git commit --fixup af8d880
    $ git log --oneline -3
    552417d fixup! Щи
    c28d784 Соль: уточнил
    af8d880 Щи

Перед отправкой `git rebase -i --autosquash main` сам поставит такие коммиты под нужные и
напишет им `fixup` — останется сохранить план:

    $ git rebase -i --autosquash main
    Successfully rebased and updated refs/heads/recipe.
    $ git log --oneline -2
    160c4b1 Соль: уточнил
    23f46c2 Щи

## Правило безопасности

Переписанные коммиты — новые коммиты. Причёсывай только то, что ещё не отправил другим (или
свою личную ветку, предупредив, что отправишь её с `git push --force-with-lease`). Почему —
в [wiki про перенос ветки](/web/wiki/bunnyton/git-rebase).

## Источники

- [Pro Git: Перезапись истории](https://git-scm.com/book/ru/v2/Инструменты-Git-Перезапись-истории) —
  amend, rebase -i, squash, разбиение коммита.
- [git-rebase](https://git-scm.com/docs/git-rebase), раздел «Interactive mode», и
  [git-commit](https://git-scm.com/docs/git-commit) (`--amend`, `--fixup`).
- [Atlassian: git rebase](https://www.atlassian.com/ru/git/tutorials/rewriting-history/git-rebase) —
  на русском, с примерами интерактивного режима.
- [Learn Git Branching](https://learngitbranching.js.org/?locale=ru_RU) — уровни про rebase -i.

---
tags: git, pull, stash, конфликт, untracked
---
# Когда git pull отказывает

`git pull` = `git fetch` (скачать) + `git merge` (влить). Слияние меняет файлы в рабочем
каталоге, поэтому сначала git проверяет: не затрёт ли он то, чего нет ни в одном коммите?
Если затрёт — он **ничего не делает** и объясняет, что мешает. Это защита, а не поломка.

## Случай 1: незакоммиченная правка в том же файле

    $ git pull
    Updating e1656ae..ddd3fea
    error: Your local changes to the following files would be overwritten by merge:
    	schedule.txt
    Please commit your changes or stash them before you merge.
    Aborting

Варианты — git сам их называет:

1. **Убрать на полку** и вернуть после:

       git stash
       git pull
       git stash pop

   Если правки в разных строках, git сложит их сам: `Auto-merging schedule.txt`. В
   соседних или тех же строках будет конфликт — его разбирают как
   [обычный конфликт слияния](/web/wiki/bunnyton/git-conflict).
2. **Закоммитить** и слить: `git commit -am "…"`, потом `git pull`. Хорошо, если правка
   уже готова.

## Случай 2: неотслеживаемый файл на пути

    $ git pull
    error: The following untracked working tree files would be overwritten by merge:
    	report.txt
    Please move or remove them before you merge.
    Aborting

Твой `report.txt` git никогда не видел — копии у него нет. Напарник прислал файл с тем же
именем. Слияние положило бы его файл на место твоего, и черновик пропал бы навсегда.

Что делать:

1. Переименуй или перенеси свой файл: `mv report.txt report-mine.txt`.
2. `git pull` — файл напарника встанет на место.
3. Сравни и реши, что взять из своего.

Обычный `git stash` неотслеживаемые файлы не берёт — нужен `git stash -u`.

## Посмотреть до слияния

Чтобы узнать, что придёт, ничего не трогая:

    git fetch
    git log --oneline main..origin/main     # чужие коммиты, которых у тебя нет
    git diff main origin/main --stat         # какие файлы они меняют

## Источники

- [Pro Git: Работа с удалёнными репозиториями](https://git-scm.com/book/ru/v2/Основы-Git-Работа-с-удалёнными-репозиториями) —
  fetch, pull, push.
- [Pro Git: Припрятывание и очистка](https://git-scm.com/book/ru/v2/Инструменты-Git-Припрятывание-и-очистка) —
  stash, в том числе `-u`.
- [git pull](https://git-scm.com/docs/git-pull) — официальная документация.
- [Atlassian: git pull](https://www.atlassian.com/git/tutorials/syncing/git-pull) — pull по
  шагам, с картинками.

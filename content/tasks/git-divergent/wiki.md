---
tags: git, pull, rebase, divergent, merge, история
---
# git pull: «divergent branches»

У тебя есть неотправленные коммиты, а на сервере — чужие. Отправить не выйдет:

    $ git push
     ! [rejected]        main -> main (fetch first)
    hint: Updates were rejected because the remote contains work that you do not
    hint: have locally.

А `git pull` в свежем git (с 2.27) останавливается и спрашивает, как сложить истории:

    $ git pull
    hint: You have divergent branches and need to specify how to reconcile them.
    hint: You can do so by running one of the following commands sometime before
    hint: your next pull:
    hint:
    hint:   git config pull.rebase false  # merge
    hint:   git config pull.rebase true   # rebase
    hint:   git config pull.ff only       # fast-forward only
    hint:
    hint: You can replace "git config" with "git config --global" to set a default
    hint: preference for all repositories. You can also pass --rebase, --no-rebase,
    hint: or --ff-only on the command line to override the configured default per
    hint: invocation.
    fatal: Need to specify how to reconcile divergent branches.

## Три ответа

| Способ | Разово | Навсегда | Что получится |
|---|---|---|---|
| слияние | `git pull --no-rebase` | `pull.rebase false` | коммит слияния, история с развилкой |
| перестройка | `git pull --rebase` | `pull.rebase true` | твои коммиты поверх чужих, прямая линия |
| только перемотка | `git pull --ff-only` | `pull.ff only` | отказ, если ветки разошлись — решай сам |

`--global` пишет настройку в `~/.gitconfig` — для всех твоих репозиториев. Без него — только
в `.git/config` текущего.

## Что выбрать

Перестройка подходит для своих **неотправленных** коммитов: история читается как прямая линия.
Многие команды так и договариваются, а на GitHub и GitLab есть защита ветки
«Require linear history» — сервер просто не примет коммит слияния.

Получилось слияние, а нужна прямая линия? Пока не отправил — верни ветку назад и повтори:

    git reset --hard ORIG_HEAD   # ORIG_HEAD — где была ветка до pull
    git pull --rebase

## Источники

- [git pull](https://git-scm.com/docs/git-pull) — официальная документация, ключи
  `--rebase`, `--ff-only` и настройка `pull.rebase`.
- [Pro Git: Перебазирование](https://git-scm.com/book/ru/v2/Ветвление-в-Git-Перебазирование) —
  чем перестройка отличается от слияния и когда её не делать.
- [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) —
  правило «Require linear history».

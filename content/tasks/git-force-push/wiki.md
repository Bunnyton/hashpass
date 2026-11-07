---
tags: git, push, force, force-with-lease, rebase, команда
---
# push --force и --force-with-lease

После `rebase`, `commit --amend` или `rebase -i` у коммитов новые хеши. Если ветка уже на
сервере, обычный push откажет:

    $ git push
     ! [rejected]        search -> search (fetch first)
    hint: Updates were rejected because the remote contains work that you do not
    hint: have locally.

## --force: заменить, не глядя

    $ git push --force
     + 247dd9f...a1d862f search -> search (forced update)

Ветка на сервере теперь — твоя. Всё, что успел отправить коллега и чего у тебя нет, из ветки
пропало. Если коммит ещё не удалён сборщиком мусора, его можно вернуть по хешу — хеш есть у
автора в `git log` или `git reflog`:

    git fetch origin 247dd9f     # если сервер разрешает забирать по хешу
    git cherry-pick 247dd9f

## --force-with-lease: заменить, только если там то, что я видел

    $ git push --force-with-lease
     ! [rejected]        search -> search (stale info)

Отказ значит: ветка на сервере уже не та, что в твоём `origin/search`. Кто-то отправил новое.
Порядок действий:

    git fetch
    git log --oneline search..origin/search   # что там нового
    git cherry-pick <хеш>                     # перенести к себе
    git push --force-with-lease

Ловушка: `git fetch` обновляет `origin/search`. Сделал fetch и не посмотрел, что пришло, —
проверка lease уже ничего не поймает. Для полной уверенности есть `--force-if-includes`.

## Правила команды

- Свои ветки, которые никто не трогает, — перестраивай и перезаписывай свободно.
- Общие ветки — только `--force-with-lease` и только после того, как посмотрел `origin/…`.
- `main` обычно защищён: сервер вообще не принимает перезапись.

## Источники

- [git push](https://git-scm.com/docs/git-push) — официальная документация, разделы
  `--force-with-lease` и `--force-if-includes`.
- [Pro Git: Опасности перебазирования](https://git-scm.com/book/ru/v2/Ветвление-в-Git-Перебазирование) —
  раздел «Опасности перемещения».
- [Atlassian: git push --force-with-lease](https://www.atlassian.com/git/tutorials/syncing/git-push) —
  разбор с примерами.

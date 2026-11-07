---
tags: git, tag, тег, релиз, push
---
# Теги релизов

Тег — метка, которая не двигается: «версия 2.0 — вот этот коммит».

    git tag -a v2.0 -m "Версия 2.0" 102c3d9   # аннотированный, на нужный коммит
    git tag                                    # список
    git show v2.0                              # кто, когда, на какой коммит

Простой тег (`git tag v2.0`) — только имя. Для релизов ставят аннотированный: у него есть
автор, дата и сообщение.

## Отправить на сервер

`git push` теги не отправляет:

    $ git push
    Everything up-to-date
    $ git push origin v2.0
     * [new tag]         v2.0 -> v2.0

Все сразу — `git push --tags`. Только аннотированные, вместе с веткой —
`git push --follow-tags`.

## Тег не на том коммите

    $ git tag -a v1.9 -m "Версия 1.9" 7d4f463
    fatal: tag 'v1.9' already exists
    $ git tag -f -a v1.9 -m "Версия 1.9" 7d4f463
    Updated tag 'v1.9' (was 7728c94)
    $ git push origin v1.9
     ! [rejected]        v1.9 -> v1.9 (already exists)
    hint: Updates were rejected because the tag already exists in the remote.
    $ git push --force origin v1.9
     + 7728c94...6e4dd9e v1.9 -> v1.9 (forced update)

Тег, который уже скачали другие, у них не обновится сам: `git fetch --tags --force`.
Поэтому git советует не перевешивать опубликованные теги, а выпустить новую версию —
`v1.9.1`. Перевешивают, только если релиз ещё никто не брал.

Удалить тег: `git tag -d v1.9` у себя и `git push origin --delete v1.9` на сервере.

## Источники

- [Pro Git: Работа с тегами](https://git-scm.com/book/ru/v2/Основы-Git-Работа-с-тегами) —
  виды тегов, отправка, удаление.
- [git tag: On Re-tagging](https://git-scm.com/docs/git-tag#_on_re_tagging) — почему
  перевешивать опубликованный тег плохо и что делать, если пришлось.
- [Семантическое версионирование](https://semver.org/lang/ru/) — как называть версии.

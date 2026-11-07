---
tags: git, submodule, подмодуль, clone, зависимости
---
# Подмодули (git submodule)

Подмодуль — каталог, в котором живёт другой git-репозиторий. Главный репозиторий хранит
адрес (в `.gitmodules`) и **коммит**, на котором подмодуль закреплён.

    $ cat .gitmodules
    [submodule "engine"]
    	path = engine
    	url = /srv/git/engine.git

## Склонировал, а каталог пустой

    $ ./play.sh
    ./play.sh: 4: .: cannot open ./engine/engine.sh: No such file
    $ git submodule status
    -d161764ef85604dde7bc330ce2c9031e5cf18861 engine
    $ git submodule update --init
    Submodule path 'engine': checked out 'd161764ef85604dde7bc330ce2c9031e5cf18861'

Сразу с подмодулями: `git clone --recurse-submodules <адрес>`. Чтобы `git pull` сам
обновлял подмодули: `git config --global submodule.recurse true`.

## Обновить подмодуль до новой версии

    $ git submodule update --remote      # или: cd engine && git switch main && git pull
    $ git status --short
     M engine
    $ git diff --submodule
    Submodule engine d161764..0dae50c:
      > Движок 1.1: комнаты в рамке
    $ git add engine && git commit -m "Движок 1.1" && git push

Без коммита в главном репозитории новая версия останется только у тебя.

## Частые сюрпризы

- Внутри подмодуля HEAD **не на ветке** (detached): `submodule update` ставит его на коммит.
  Коммитишь в подмодуле — сначала `git switch main`.
- `fatal: transport 'file' not allowed` — с git 2.38 подмодули по локальному пути запрещены
  ради безопасности. Для своих путей: `git config --global protocol.file.allow always`.
- Альтернативы подмодулям: `git subtree` и менеджеры пакетов (pip, npm, go modules).

## Источники

- [Pro Git: Подмодули](https://git-scm.com/book/ru/v2/Инструменты-Git-Подмодули) — подробно,
  с примерами.
- [git submodule](https://git-scm.com/docs/git-submodule) — официальная документация.

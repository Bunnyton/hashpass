---
tags: git, коммит, история, основы
---
# Первый git-репозиторий

**git** — система контроля версий: она помнит каждое сохранённое состояние проекта, кто его
сделал, когда и зачем. Вместо `диплом_финал_точно_финал.docx` — один каталог и цепочка
коммитов, к любому из которых можно вернуться или сравнить с соседним.

Главное отличие git от старых систем (CVS, Subversion): **полная история лежит у каждого**.
Коммитить, смотреть историю и сравнивать версии можно без сети и без сервера.

## Репозиторий: git init

Репозиторий — обычный каталог, у которого git ведёт историю. Заводят его один раз,
**находясь в каталоге проекта**: git, как и `ls`, работает там, где ты стоишь.

    $ git init
    Initialized empty Git repository in /tmp/mytest-git/w.o6HO/recipes/.git/
    $ ls -a
    .
    ..
    .git
    bliny.txt
    borsch.txt

Вся история — в скрытом `.git`. Удалишь его — файлы останутся, истории не станет. Читай строку
`Initialized … in` внимательно: она говорит, **где** появился репозиторий. Если там домашний
каталог, а не проект — ты стоял не там.

## Кто ты: имя и почта

Каждый коммит подписан. Пока git не знает автора, коммит не выйдет:

    *** Please tell me who you are.

    Run

      git config --global user.email "you@example.com"
      git config --global user.name "Your Name"

Представляются один раз: `--global` пишет в `~/.gitconfig`, и это работает во всех
репозиториях. Без `--global` — только в текущем (удобно, если для работы нужна другая почта).
Проверить: `git config user.name`.

## Индекс: что войдёт в коммит

Между файлами и коммитом есть промежуточный список — **индекс** (staging area). Коммит берёт
только то, что лежит в индексе. Новые файлы git видит, но не берёт:

    $ git status
    On branch main

    No commits yet

    Untracked files:
      (use "git add <file>..." to include in what will be committed)
    	bliny.txt
    	borsch.txt

    nothing added to commit but untracked files present (use "git add" to track)

После `git add bliny.txt` файл переезжает в группу «Changes to be committed»:

    Changes to be committed:
      (use "git rm --cached <file>..." to unstage)
    	new file:   bliny.txt

    Untracked files:
      (use "git add <file>..." to include in what will be committed)
    	borsch.txt

`git add .` кладёт в индекс всё в текущем каталоге. Зачем вообще индекс? Чтобы из десятка
правок собрать в коммит только относящиеся к делу, а остальное закоммитить отдельно.

`git status` — лучший друг: он говорит, что где лежит, и в скобках подсказывает следующую
команду. Короткий вид — `git status -s` (`??` — новый, `A` — добавлен, `M` — изменён).

## Коммит

    $ git commit -m "Первые рецепты"
    [main (root-commit) 666081c] Первые рецепты
     2 files changed, 4 insertions(+)
     create mode 100644 bliny.txt
     create mode 100644 borsch.txt

`666081c` — начало хеша, имени коммита. Сообщение пиши для себя через полгода: «Борщ:
картошка», а не «правки». Без `-m` git откроет редактор для сообщения.

Файл, который git уже знает, после правки снова надо положить в индекс. Сокращение — ключ
`-a`: он сам добавит изменённые **знакомые** файлы (новые — всё равно через `git add`):

    $ git commit -am "Борщ: картошка"
    [main 68e451d] Борщ: картошка
     1 file changed, 1 insertion(+), 1 deletion(-)

## Что изменилось: log, diff, show

    $ git log --oneline
    68e451d Борщ: картошка
    666081c Первые рецепты

Полный `git log` добавит автора и дату. Что поменяно в файлах, но ещё не закоммичено, —
`git diff` (а что уже в индексе — `git diff --staged`). Коммит целиком — `git show <хеш>`,
без хеша — последний:

    $ git show
    commit 68e451d6545d5a6abec0fe638280a7c239f36762
    Author: Аня <anya@example.com>
    Date:   Mon Oct 5 10:10:00 2026 +0300

        Борщ: картошка

    diff --git a/borsch.txt b/borsch.txt
    index aa41f3f..8368554 100644
    --- a/borsch.txt
    +++ b/borsch.txt
    @@ -1,2 +1,2 @@
     Борщ
    -свёкла, капуста
    +свёкла, капуста, картошка

Это формат **diff**: `-` — строка, какой была, `+` — какой стала, без знака — соседние строки
для ориентира. `@@ -1,2 +1,2 @@` — с какой строки и сколько строк показано до и после.

## Где пригодится

- конфиги сервера (`/etc/nginx`, свои dotfiles) — видно, что и когда поменял;
- скрипты, заметки, тексты — любые текстовые файлы;
- дальше по курсу: [поиск по истории](/web/wiki/bunnyton/git-log),
  [ветки](/web/wiki/bunnyton/git-branch), [сервер](/web/wiki/bunnyton/git-remote).

## Источники

- [Pro Git: О системе контроля версий](https://git-scm.com/book/ru/v2/Введение-О-системе-контроля-версий) —
  история и зачем это всё.
- [Pro Git: Первоначальная настройка](https://git-scm.com/book/ru/v2/Введение-Первоначальная-настройка-Git) —
  имя, почта, редактор.
- [Pro Git: Запись изменений в репозиторий](https://git-scm.com/book/ru/v2/Основы-Git-Запись-изменений-в-репозиторий) —
  status, add, commit, diff подробно.
- [git init](https://git-scm.com/docs/git-init) и [git commit](https://git-scm.com/docs/git-commit) —
  официальная документация.
- [githowto.com](https://githowto.com/ru) — пошаговый курс на русском.

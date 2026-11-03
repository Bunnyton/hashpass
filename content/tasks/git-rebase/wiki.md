---
tags: git, rebase, ветки, история
---
# Перенос ветки: git rebase

Ты сделал ветку под свою задачу, а команда тем временем ушла вперёд в `main`. Склеить линии
можно двумя путями: **слить** (`git merge`) или **перенести** (`git rebase`). Здесь — как
работает перенос, что делать с конфликтом посреди него и как потом влить ветку так, чтобы
история осталась прямой.

## Как увидеть развилку

Сначала посмотри, что вообще происходит. Граф всех веток — `git log --oneline --graph --all`
(или твой короткий псевдоним `git lg`). Пример: блог, ветка `tags` отошла от `main` после
первого коммита, а в `main` с тех пор два новых:

    $ git log --oneline --graph --all
    * 287ff3b RSS-лента
    * 3360b0c Комментарии
    | * 3c47b93 NEWS: теги
    | * f794f99 Теги: модель
    |/
    * 84c4089 Начало

Две линии от одного коммита — это и есть развилка.

## Слить или перенести

`git merge` склеивает линии **коммитом слияния** — у него два родителя:

    $ git merge --no-edit f
    Merge made by the 'ort' strategy.
    $ git log --oneline --graph
    *   7f232b6 Merge branch 'f'
    |\
    | * e78683a B на ветке
    * | f1f4d6a C в main
    |/
    * d359308 A

Честно, но когда веток десятки, граф превращается в паутину. Поэтому многие команды
договариваются (обычно в `CONTRIBUTING.md`): перед слиянием ветку **переносят** на свежий
main, и история остаётся прямой линией.

## Что делает rebase

`git rebase <ветка>` — «поставь мою текущую ветку на вершину вот этой»:

1. git находит общего предка (на рисунке выше — `Начало`);
2. откладывает твои коммиты после него;
3. ставит ветку на вершину другой ветки;
4. повторяет отложенные коммиты по одному, от старого к новому.

Изменения те же, а коммиты — **новые**, с новыми хешами: у них другой родитель и другое
время. Отсюда золотое правило: переносят только свои ветки, которые ещё никто не забрал.
Перепишешь опубликованную — у коллег история разойдётся с твоей.

## Конфликт посреди переноса

Если твой коммит и main поменяли одно и то же место, git остановится на этом коммите:

    $ git rebase main
    Rebasing (1/2)Rebasing (2/2)Auto-merging NEWS
    CONFLICT (content): Merge conflict in NEWS
    error: could not apply 3c47b93... NEWS: теги
    hint: Resolve all conflicts manually, mark them as resolved with
    hint: "git add/rm <conflicted_files>", then run "git rebase --continue".
    hint: You can instead skip this commit: run "git rebase --skip".
    hint: To abort and get back to the state before "git rebase", run "git rebase --abort".

Перенос стоит на паузе. `git status` всегда скажет, где ты и что дальше:

    $ git status
    interactive rebase in progress; onto 287ff3b
    ...
    You are currently rebasing branch 'tags' on '287ff3b'.
      (fix conflicts and then run "git rebase --continue")
    ...
    	both modified:   NEWS

В файле — обе версии между метками:

    $ cat NEWS
    Изменения:
    <<<<<<< HEAD
    - комментарии
    =======
    - теги к постам
    >>>>>>> 3c47b93 (NEWS: теги)

Порядок тот же, что при конфликте слияния: оставь правильный итог, убери метки, `git add`
файла. Только дальше не `git commit`, а продолжение переноса — git сам назвал ключ. Три ключа
на все случаи:

| Ключ | Что делает |
|---|---|
| `--continue` | конфликт решён, иди дальше |
| `--skip` | выбросить этот коммит и идти дальше |
| `--abort` | отменить перенос целиком, ветка как была |

Внимание: при переносе `HEAD` в метках — это уже **main** (на него ставят), а твой коммит —
внизу. При слиянии наоборот. Не путай, когда выбираешь, что оставить.

## Влить без коммита слияния

Когда ветка продолжает main, сливать нечего — git просто передвигает метку `main` вперёд.
Это **перемотка** (fast-forward):

    $ git merge tags
    Updating 287ff3b..dbf73c4
    Fast-forward
     NEWS     | 1 +
     tags.txt | 1 +
    $ git log --oneline --graph
    * dbf73c4 NEWS: теги
    * 0375205 Теги: модель
    * 287ff3b RSS-лента
    * 3360b0c Комментарии
    * 84c4089 Начало

Вливают в ту ветку, **в которой стоишь**. Подстраховка — `--ff-only`: если перемотка
невозможна, git откажется, а не сделает коммит слияния:

    $ git merge --ff-only f
    fatal: Not possible to fast-forward, aborting.

## Если всё пошло не так

`git reflog` помнит каждое положение `HEAD` — в том числе до слияния или переноса:

    $ git reflog | head -3
    7f232b6 HEAD@{0}: merge f: Merge made by the 'ort' strategy.
    f1f4d6a HEAD@{1}: commit: C в main
    d359308 HEAD@{2}: checkout: moving from f to main

`git reset --hard <хеш>` вернёт ветку туда ([подробнее про reflog](/web/wiki/bunnyton/git-reflog)).

Ещё пригодится: `git pull --rebase` забирает чужие коммиты и ставит твои поверх, без лишних
слияний, а `git rebase -i` переписывает свои коммиты ([следующее задание](/web/wiki/bunnyton/git-squash)).

## Источники

- [Pro Git: Перебазирование](https://git-scm.com/book/ru/v2/Ветвление-в-Git-Перебазирование) —
  глава книги на русском, с картинками и «опасностями перебазирования».
- [git-rebase](https://git-scm.com/docs/git-rebase) и [git-merge](https://git-scm.com/docs/git-merge) —
  официальная справка (то же, что `git rebase --help`).
- [Atlassian: слияние или перебазирование](https://www.atlassian.com/ru/git/tutorials/merging-vs-rebasing) —
  когда что выбирать.
- [Learn Git Branching](https://learngitbranching.js.org/?locale=ru_RU) — интерактивные
  упражнения, ветки рисуются прямо на экране.

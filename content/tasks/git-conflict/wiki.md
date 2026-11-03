---
tags: git, слияние, конфликт, ветки
---
# Конфликты слияния: стороны и стратегии

Простой конфликт разбирают руками: открыл файл, оставил нужное, убрал метки, `git add`,
`git commit` (это было в [задании про ветки](/web/wiki/bunnyton/git-branch)). Но если одну и ту
же вещь переписали в двух ветках целиком, конфликтов в файле — десятки, и ответ во всех
местах один: «бери эту версию». Руками так не разбирают.

## Стороны конфликта

У каждой стороны конфликта есть имя:

- **ours** («наша») — ветка, в которой ты стоишь и **в которую** вливаешь (`HEAD`);
- **theirs** («их») — ветка, которую вливаешь.

    $ cat limits.conf
    workers=4
    <<<<<<< HEAD
    timeout=45
    =======
    timeout=60
    >>>>>>> ops
    log=info
    cache=on
    retries=5

Над `=======` — ours, под ним — theirs. Обрати внимание: `retries=5` (наша правка) и
остальные строки без спора git уже слил сам — конфликт только там, где обе стороны тронули
одно место.

Подсмотреть ещё и **общего предка** — как было до обеих правок — помогает стиль `zdiff3`:

    $ git -c merge.conflictStyle=zdiff3 merge ops
    Auto-merging limits.conf
    CONFLICT (content): Merge conflict in limits.conf
    Automatic merge failed; fix conflicts and then commit the result.
    $ cat limits.conf
    workers=4
    <<<<<<< HEAD
    timeout=45
    ||||||| 4ffb3c7
    timeout=30
    =======
    timeout=60
    >>>>>>> ops

Включить навсегда: `git config --global merge.conflictStyle zdiff3`.

## Что в конфликте — спроси git status

    $ git status -s
    UU guide.txt

`UU` — «обе стороны изменили», файл ждёт решения. После `git add` он станет обычным
`M`. Слияние закончится коммитом, только когда в списке не останется ни одного `UU`.
`git log --merge` покажет коммиты обеих сторон, которые трогали спорные файлы.

## Файл одной стороны целиком: checkout --ours / --theirs

Пока слияние не закончено, `git checkout` умеет положить в каталог файл в версии одной из
сторон — целиком, без меток:

    $ git checkout --theirs guide.txt
    Updated 1 path from the index
    $ cat guide.txt
    Как установить
    Как запустить
    Как настроить
    $ git status -s
    UU guide.txt
    $ git add guide.txt
    $ git status -s
    M  guide.txt

Меток нет, но git всё ещё считает файл спорным — пока не сделаешь `git add`. Новый вариант
той же команды — `git restore --ours/--theirs файл`.

В одном слиянии можно мешать способы: один файл — целиком одной стороны, другой — руками.

## Стратегия слияния: -X ours / -X theirs

Слияние выполняет **стратегия** — сейчас по умолчанию `ort`. Ей можно заранее сказать, кого
слушать в спорных строках, — ключом `-X`:

    $ git merge -X theirs --no-edit ops
    Auto-merging limits.conf
    Merge made by the 'ort' strategy.
     limits.conf | 2 +-
     1 file changed, 1 insertion(+), 1 deletion(-)
    $ cat limits.conf
    workers=4
    timeout=60
    log=info
    cache=on
    retries=5

Спорная строка — их (`timeout=60`), а наша бесспорная правка `retries=5` осталась. В этом
разница:

| Способ | Что берёт |
|---|---|
| `checkout --theirs файл` | файл другой стороны **целиком**, наши правки в нём пропадут |
| `merge -X theirs` | их версию только в **спорных** местах, остальное сливает как обычно |
| `merge -s ours` (стратегия, не настройка!) | **ничего** из их ветки: история «влита», файлы наши |

`-s ours` и `-X ours` легко спутать — первая выкидывает чужие правки полностью.

## Как начать заново

Слияние пошло не так — `git merge --abort` вернёт всё как было до него. Потом можно влить
снова, уже с нужным ключом. Уже закоммиченное слияние отменяют
[журналом](/web/wiki/bunnyton/git-reflog) или `git revert -m 1`.

## Подвох с rebase

В `git rebase` стороны меняются местами: «ours» там — ветка, **на которую** переносишь, а
«theirs» — твои переносимые коммиты. Перед `--ours/--theirs` в rebase перечитай это дважды.

## Источники

- [Pro Git: Продвинутое слияние](https://git-scm.com/book/ru/v2/Инструменты-Git-Продвинутое-слияние) —
  стороны, `--ours/--theirs`, `-X`, стили конфликтов, отмена слияния.
- [git merge](https://git-scm.com/docs/git-merge) — разделы MERGE STRATEGIES и HOW CONFLICTS
  ARE PRESENTED.
- [git checkout](https://git-scm.com/docs/git-checkout) — ключи `--ours` и `--theirs`.
- [man git-merge на man7.org](https://man7.org/linux/man-pages/man1/git-merge.1.html).

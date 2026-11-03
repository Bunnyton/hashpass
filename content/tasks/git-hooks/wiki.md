---
tags: git, хуки, скрипты, проверки
---
# Хуки git: проверки, которые git делает сам

**Хук** (hook, «крючок») — обычный скрипт, который git запускает сам в нужный момент: перед
коммитом, после слияния, перед отправкой. Хук может проверить, что ты делаешь, и **отказать**.
Так команды ловят пароли в коде, сообщения «fix» и пробелы в конце строк — до того, как это
попало в историю.

## Где живут хуки

У каждого репозитория свой каталог `.git/hooks`. `git init` кладёт туда примеры:

    $ ls .git/hooks
    applypatch-msg.sample
    commit-msg.sample
    fsmonitor-watchman.sample
    post-update.sample
    pre-applypatch.sample
    pre-commit.sample
    pre-merge-commit.sample
    prepare-commit-msg.sample
    pre-push.sample
    pre-rebase.sample
    pre-receive.sample
    push-to-checkout.sample
    sendemail-validate.sample
    update.sample

С окончанием `.sample` они не работают. Хук называется **ровно по событию**, без расширения:

| Хук | Когда | Что может |
|---|---|---|
| `pre-commit` | перед коммитом, до сообщения | проверить, что войдёт в коммит |
| `commit-msg` | сообщение написано | проверить или поправить сообщение |
| `pre-push` | перед `git push` | прогнать тесты, не пустить push |
| `post-commit`, `post-merge` | после действия | что-то сделать, отменить уже нельзя |

## Как git решает

1. Ты делаешь действие — например, `git commit`.
2. git ищет в `.git/hooks` файл с именем события.
3. Файл есть и **исполняемый** — запускает. Код выхода 0 — действие идёт дальше, не 0 — git
   останавливается. Что хук напишет в stderr, человек увидит.

Без права на запуск git хук не тронет и честно предупредит — а коммит пройдёт:

    $ git commit -m "Привет"
    hint: The '.git/hooks/pre-commit' hook was ignored because it's not set as executable.
    hint: You can disable this warning with `git config advice.ignoredHook false`.
    [main (root-commit) d89534c] Привет

Лечится `chmod +x .git/hooks/pre-commit` (про права — в [wiki о chmod](/web/wiki/bunnyton/chmod-basics)).

## pre-commit: что войдёт в коммит

В момент `pre-commit` коммита ещё нет — есть **индекс**, то, что ты подготовил `git add`.
Его показывает `git diff --cached`: добавленные строки начинаются с `+`. Хук — обычный
скрипт: проверка, понятное сообщение в stderr, `exit 1`. Пример — не пускать пробелы в конце
строк (у git для этого даже есть готовая проверка `--check`):

```sh
#!/bin/sh
# не пускать в коммит пробелы в конце строк
if ! git diff --cached --check; then
    echo "pre-commit: уберите пробелы в конце строк" >&2
    exit 1
fi
```

    $ git commit -m "Привет"
    a.txt:1: trailing whitespace.
    +hello
    pre-commit: уберите пробелы в конце строк
    $ echo $?
    1

Коммита нет. Проверяй хук **делом**: нарочно сделай плохой коммит (должен отказать) и
хороший (должен пройти). Хук, который отказывает всем, тоже сломан.

Для поиска в выводе отлично подходит `grep -q` — молчит и отвечает только кодом выхода, а
`-i` не различает регистр ([регулярки в grep](/web/wiki/bunnyton/regex)).

## commit-msg: проверка сообщения

Сообщение git сначала пишет во временный файл, а путь к нему передаёт хуку **первым
аргументом** — в скрипте это `$1`. Пример — сообщение не короче 10 символов:

```sh
#!/bin/sh
first=$(head -n 1 "$1")
if [ ${#first} -lt 10 ]; then
    echo "commit-msg: «$first» — слишком коротко, опиши, что сделано" >&2
    exit 1
fi
```

    $ git commit -m "fix"
    commit-msg: «fix» — слишком коротко, опиши, что сделано
    $ git commit -m "Ответ бота на /start"
    [main 7088f58] Ответ бота на /start
     1 file changed, 1 insertion(+)

Хуки работают вместе: при коммите сначала `pre-commit`, потом `commit-msg` — каждый на своём
шаге. Многие команды требуют номер задачи из трекера в начале сообщения: тогда по истории
сразу видно, зачем сделан коммит.

## Аварийный люк

`git commit --no-verify` (или `-n`) пропускает `pre-commit` и `commit-msg`. Это на крайний
случай, а не обычная дорога — поэтому важные проверки дублируют на сервере
([wiki про серверные хуки](/web/wiki/bunnyton/git-deploy)).

## Хуки для всей команды

`.git/hooks` не попадает ни в коммиты, ни в клон — каждый ставит хуки себе сам. Поэтому
хуки кладут в обычный каталог репозитория и включают одной настройкой:

    $ git config core.hooksPath .githooks
    $ git config core.hooksPath
    .githooks

Есть и готовые менеджеры хуков — например, [pre-commit](https://pre-commit.com/): набор
проверок описывается в файле, а программа сама их ставит и запускает.

## Источники

- [githooks](https://git-scm.com/docs/githooks) — официальный список всех хуков: когда
  запускается, что получает на вход.
- [Pro Git: Хуки в Git](https://git-scm.com/book/ru/v2/Настройка-Git-Хуки-в-Git) — глава на
  русском, клиентские и серверные хуки.
- [Atlassian: хуки Git](https://www.atlassian.com/ru/git/tutorials/git-hooks) — примеры на
  русском.
- [pre-commit.com](https://pre-commit.com/) — фреймворк для общих хуков команды.

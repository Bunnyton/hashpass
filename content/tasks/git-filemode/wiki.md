---
tags: git, права, chmod, diff, filemode
---
# Изменены все файлы, а правка одна

Проект скопировали на флешку и обратно, открыли в Windows, распаковали из zip — и
`git status` вдруг считает изменёнными десятки файлов. Чаще всего виноваты **права**.

## git хранит один бит прав

Из всех прав Linux git помнит только, исполняемый ли файл:

| Режим | Что значит |
|---|---|
| `100644` | обычный файл |
| `100755` | исполняемый (скрипт) |

FAT и exFAT прав не хранят вовсе: при копировании обратно все файлы становятся
`rwxr-xr-x`. git видит у конфигов 755 вместо 644 и считает их изменёнными.

## Как это выглядит

    $ git diff nginx/nginx.conf
    diff --git a/nginx/nginx.conf b/nginx/nginx.conf
    old mode 100644
    new mode 100755

Две строки про mode и ни одной строки с `+`/`-` — содержимое не менялось.

## Найти настоящую правку в шуме

Сводка показывает, сколько строк поменялось в каждом файле:

    $ git diff --stat
     README.md                 | 0
     logrotate/app.conf        | 2 +-
     ...
     36 files changed, 1 insertion(+), 1 deletion(-)

`0` — только права. `2 +-` — вот она, настоящая правка.

## Закоммитить только её

Осторожно: `git add` берёт файл вместе с новыми правами, и commit скажет об этом:

    $ git commit -m "logrotate: 14 дней"
     1 file changed, 1 insertion(+), 1 deletion(-)
     mode change 100644 => 100755 logrotate/app.conf

Сначала верни права (`chmod 644 файл`), потом коммить. Уже закоммитил —
`chmod 644 файл` и [git commit --amend](/web/wiki/bunnyton/git-amend).

## Вернуть права остальным

`git restore .` возвращает файлы к последнему коммиту — вместе с правами. Только **после**
того, как настоящая правка в коммите: незакоммиченное `restore` стирает безвозвратно.

## Не замечать права вовсе

Если репозиторий живёт на файловой системе без прав (флешка, общий каталог с Windows):

    git config core.fileMode false

Тогда git перестанет сравнивать бит исполняемости в этом репозитории.

## Источники

- [git config: core.fileMode](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefileMode) —
  официальная документация настройки.
- [git diff](https://git-scm.com/docs/git-diff) — `--stat`, строки `old mode`/`new mode`.
- [Pro Git: Объекты Git](https://git-scm.com/book/ru/v2/Git-изнутри-Объекты-Git) — режимы
  `100644`/`100755` в деревьях.
- [man chmod](https://man7.org/linux/man-pages/man1/chmod.1.html) — права файлов в Linux.

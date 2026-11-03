---
tags: файлы, cp, копирование
---
# cp: копирование файлов и каталогов

`cp` (copy) делает копию: оригинал остаётся на месте, а копия живёт своей жизнью — правишь
одну, другая не замечает.

    cp откуда куда

## Файл в каталог

Если второй аргумент — существующий каталог, копия ляжет **внутрь** него под тем же именем:

    $ cp flowers.txt garden/
    $ ls . garden
    .:
    flowers.bak
    flowers.txt
    garden

    garden:
    flowers.txt

Косая в конце (`garden/`) необязательна, но полезна: если каталога вдруг нет, `cp` не создаст
вместо него файл с таким именем, а скажет об ошибке.

## Файл под новым именем

Если второй аргумент — новое имя, получится копия рядом, с другим именем. Так делают
резервную копию перед правкой конфига:

    $ cp flowers.txt flowers.bak

(Это её мы и видели в списке выше.)

Если файл с таким именем **уже есть**, `cp` молча запишет поверх. Защита — ключи:

| Ключ | Что делает |
|---|---|
| `-i` | спросит: `cp: overwrite 'flowers.bak'?` |
| `-n` | существующий файл не тронет |
| `-b` | старый сохранит как `имя~` |
| `-v` | покажет, что скопировал: `'flowers.txt' -> 'flowers.bak'` |

## Каталог целиком

Каталог — не файл, и просто так `cp` его не берёт:

    $ cp garden archive
    cp: -r not specified; omitting directory 'garden'

Сообщение уже говорит, чего не хватило: ключа **рекурсии** `-r` (recursive) — «зайди внутрь и
скопируй всё, что там, со всеми подкаталогами». `-R` — то же самое.

    $ cp -rv garden summer
    'garden' -> 'summer'
    'garden/flowers.txt' -> 'summer/flowers.txt'

## Ловушка: копия внутрь копии

Куда ляжет каталог, зависит от того, **есть ли уже** каталог назначения:

    $ cp -r garden archive
    $ ls archive
    flowers.txt
    $ cp -r garden archive
    $ ls archive
    flowers.txt
    garden

Первый раз `archive` не было — он стал копией `garden`. Второй раз `archive` уже был — и
`garden` целиком уехал **внутрь** него. После копирования всегда загляни в результат через `ls`.

## Ошибки cp

    $ cp nosuch.txt garden/
    cp: cannot stat 'nosuch.txt': No such file or directory

`cannot stat` — «не нашёл, что копировать»: проверь имя и путь через `ls`.

## cp или mv

`cp` оставляет оригинал, `mv` — забирает. Нужна вторая версия файла — `cp`; нужно просто
передвинуть — [`mv`](/web/wiki/bunnyton/mv-basics). Больше про копирование деревьев —
[cp-more](/web/wiki/bunnyton/cp-more).

## Источники

- [`man 1 cp`](https://man7.org/linux/man-pages/man1/cp.1.html) — все ключи.
- [GNU Coreutils — cp invocation](https://www.gnu.org/software/coreutils/manual/coreutils.html#cp-invocation)
  — подробно, с тонкостями.
- [Команда cp в Linux — Losst](https://losst.pro/komanda-cp-v-linux) — по-русски, с примерами.
- [explainshell.com](https://explainshell.com/) — разберёт любую команду cp по ключам.

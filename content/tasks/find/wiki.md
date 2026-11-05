---
tags: файлы, find, поиск, шаблоны
---
# find: поиск файлов по имени, типу, глубине и не только

`find` обходит дерево каталогов и печатает всё, что подходит под условия. Условий у него —
вагон: имя, тип, глубина, размер, время, владелец, права. Здесь — основа и то, что встречается
в задании.

    find где условия

Ключи у `find` необычные: длинные слова, но с **одним** дефисом — `-name`, `-type`.

## Без условий — всё дерево

Пример ниже — на таком дереве:

    $ find shop
    shop
    shop/archive
    shop/price.txt
    shop/veg
    shop/veg/Potato.TXT
    shop/veg/carrot.md
    shop/fruit
    shop/fruit/apple.txt
    shop/fruit/citrus
    shop/fruit/citrus/orange.md
    shop/fruit/citrus/lemon.txt

Порядок — как каталоги лежат на диске, не по алфавиту. Нужен порядок — добавь `| sort`.

## -name — по имени

    $ find shop -name '*.txt'
    shop/price.txt
    shop/fruit/apple.txt
    shop/fruit/citrus/lemon.txt
    $ find shop -iname '*.txt'
    shop/price.txt
    shop/veg/Potato.TXT
    shop/fruit/apple.txt
    shop/fruit/citrus/lemon.txt

`*` — любые символы, `?` — один символ. `-iname` не различает регистр. Шаблон бери в
**кавычки**, иначе bash развернёт звёздочку сам, по текущему каталогу, и find получит не то:

    $ cd shop; find . -name *.txt
    ./price.txt

Здесь bash подставил `price.txt`, и find искал только это имя. А будь в каталоге два `.txt`:

    $ touch b.txt; find . -name *.txt
    find: paths must precede expression: `price.txt'
    find: possible unquoted pattern after predicate `-name'?

## Глубина: -maxdepth и -mindepth

Сам стартовый каталог — глубина 0, то, что в нём, — 1, и так далее. `-maxdepth N` не спускается
глубже N, `-mindepth N` не показывает то, что мельче N:

    $ find shop -maxdepth 1
    shop
    shop/archive
    shop/price.txt
    shop/veg
    shop/fruit
    $ find shop -mindepth 3
    shop/fruit/citrus/orange.md
    shop/fruit/citrus/lemon.txt

Вместе они вырезают «этажи» дерева с двух сторон.

## -type — файл или каталог

`-type f` — обычные файлы, `-type d` — каталоги, `-type l` — символьные ссылки:

    $ find shop -type d
    shop
    shop/archive
    shop/veg
    shop/fruit
    shop/fruit/citrus

## И, или, не

Условия подряд — это **«и»**: должны выполниться все.

    $ find shop -type f -name 'o*'
    shop/fruit/citrus/orange.md

`-o` — **«или»**. Но «и» связывает сильнее, поэтому без скобок условие слева прилипает только к
своей половине:

    $ find shop -type f -name '*.md' -o -name 'a*'
    shop/archive
    shop/veg/carrot.md
    shop/fruit/apple.txt
    shop/fruit/citrus/orange.md

Каталог `archive` пролез: читается как «(файл и `*.md`) или `a*`». Скобки собирают группу; их
нужно экранировать — `\(` и `\)` (с пробелами вокруг), иначе их заберёт bash:

    $ find shop -type f \( -name '*.md' -o -name 'a*' \)
    shop/veg/carrot.md
    shop/fruit/apple.txt
    shop/fruit/citrus/orange.md

`-not` (или `!`) переворачивает условие, стоящее сразу после него:

    $ find shop -type f -not -name '*.txt'
    shop/veg/Potato.TXT
    shop/veg/carrot.md
    shop/fruit/citrus/orange.md

## -empty и другие проверки

`-empty` — пустой файл или пустой каталог:

    $ find shop -empty
    shop/archive
    shop/veg/carrot.md
    shop/fruit/apple.txt

Ещё полезное: `-size +10M` (больше 10 МиБ), `-mtime -1` (менялся за сутки), `-user имя`,
`-newer файл`. Полный список и действия над находками (`-exec`, `-delete`) — в
[шпаргалке](wiki/cheatsheet.md).

## Ошибки find

    $ find -name '*.md' shop
    find: paths must precede expression: `shop'
    find: possible unquoted pattern after predicate `-name'?
    $ find shop -nmae x
    find: unknown predicate `-nmae'

Сначала где, потом условия; и проверь написание ключа.

## Источники

- [`man 1 find`](https://man7.org/linux/man-pages/man1/find.1.html) — разделы TESTS, OPERATORS,
  ACTIONS.
- [Команда find в Linux — Losst](https://losst.pro/komanda-find-v-linux) — много примеров
  по-русски.
- [`man 7 glob`](https://man7.org/linux/man-pages/man7/glob.7.html) — шаблоны `*`, `?`, `[...]`
  в `-name`.

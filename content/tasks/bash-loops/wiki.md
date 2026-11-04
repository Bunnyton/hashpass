---
tags: bash, циклы, for, while, кавычки, скрипты
---
# Циклы и кавычки в bash

Цикл — способ сказать «сделай это для каждого». Сто файлов, тысяча строк журнала, список
серверов — команда пишется один раз. А главная ловушка bash ждёт как раз в циклах: имена с
пробелами.

## for — по списку

    for ПЕРЕМЕННАЯ in СПИСОК; do
        команды
    done

Список — слова, шаблон файлов или вывод команды. Шаблон оболочка раскрывает сама и отдаёт имена
**целиком**:

```
$ for f in *.JPG; do echo нашёл: $f; done
нашёл: 2024-05-09 Парад 001.JPG
нашёл: 2024-05-09 Парад 002.JPG
нашёл: IMG 0001.JPG
```

Перед опасной командой ставят `echo` — цикл покажет, что сделал бы:

```
$ for f in *.JPG; do echo mv "$f" "${f%.JPG}.jpg"; done
mv 2024-05-09 Парад 001.JPG 2024-05-09 Парад 001.jpg
mv 2024-05-09 Парад 002.JPG 2024-05-09 Парад 002.jpg
mv IMG 0001.JPG IMG 0001.jpg
```

Счётчик — в стиле C:

```
$ for ((i = 0; i < 3; i++)); do echo i=$i; done
i=0
i=1
i=2
```

## while — пока условие верно

`while` повторяет тело, пока команда-условие успешна:

```
$ n=3; while (( n > 0 )); do echo $n; n=$((n - 1)); done; echo пуск
3
2
1
пуск
```

Самый частый `while` — чтение файла по строкам:

```
$ while IFS= read -r n; do echo "[$n]"; done < list.txt
[отчёт за май.txt]
[список дел.txt]
```

- `read` читает одну строку и успешен, пока строки есть;
- `< list.txt` после `done` подаёт файл на вход всему циклу;
- `IFS=` не срезает пробелы по краям, `-r` не трогает обратные косые.

`break` выходит из цикла, `continue` переходит к следующему кругу.

## Разбиение на слова — почему нужны кавычки

После подстановки `$f`, `$(команда)` bash **режет результат по пробелам** (по символам из `IFS`) и
раскрывает в нём шаблоны. Имя с пробелами превращается в несколько аргументов:

```
$ f="IMG 0001.JPG"; mv $f new.jpg
mv: target 'new.jpg': No such file or directory
```

`mv` получил три аргумента: `IMG`, `0001.JPG`, `new.jpg` — и решил, что `new.jpg` — каталог.
`"$f"` в двойных кавычках — всегда одно слово.

Та же беда с `$(ls)` и `$(cat)`:

```
$ for f in $(ls *.JPG); do echo "[$f]"; done
[2024-05-09]
[Парад]
[001.JPG]
...
$ for n in $(cat list.txt); do echo "[$n]"; done
[отчёт]
[за]
[май.txt]
[список]
[дел.txt]
```

Правила:
1. Переменная с именем файла — в двойных кавычках: `"$f"`, `"${f%.JPG}.jpg"`.
2. Файлы перебирают шаблоном (`*.JPG`), а не `$(ls)`.
3. Строки файла читают `while read`, а не `for … in $(cat)`.

## Шаблон, который ничего не нашёл

Если файлов по шаблону нет, bash оставляет шаблон **как есть** — и цикл пройдёт один раз с
буквальным `*.png`:

```
$ for f in *.png; do echo "[$f]"; done
[*.png]
$ shopt -s nullglob; for f in *.png; do echo "[$f]"; done; echo конец
конец
```

В скриптах либо включают `nullglob`, либо проверяют `[ -e "$f" ] || continue`.

## Кусок значения: `${…}`

```
$ name=report.tar.gz; echo ${name%.gz} ${name%%.*} ${name#*.} ${name:0:3} ${#name}
report.tar report tar.gz rep 13
```

| Запись | Что делает |
|---|---|
| `${v%шаблон}` | отрезать самый короткий хвост по шаблону |
| `${v%%шаблон}` | отрезать самый длинный хвост |
| `${v#шаблон}`, `${v##шаблон}` | то же с начала |
| `${v:начало:длина}` | подстрока, отсчёт с 0 |
| `${#v}` | длина |
| `${v/было/стало}` | замена первого вхождения (`//` — всех) |

## Почему `mv *.JPG *.jpg` не работает

Шаблоны раскрывает оболочка: `mv` получает все `.JPG`, за ними все существующие `.jpg`, и
последний аргумент считает целью:

```
$ mv *.JPG *.jpg
mv: target 'IMG 0001.JPG': Not a directory
```

Пакетное переименование — это цикл (или утилиты `rename`/`mmv`, которых может не быть на сервере).

## Источники

- [BashPitfalls](https://mywiki.wooledge.org/BashPitfalls) — пункты 1–3 как раз про
  `for f in $(ls)` и кавычки.
- [Word Splitting](https://mywiki.wooledge.org/WordSplitting) и
  [Quotes](https://mywiki.wooledge.org/Quotes) — Greg's Wiki.
- [Как читать файл по строкам — BashFAQ/001](https://mywiki.wooledge.org/BashFAQ/001).
- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), разделы
  Compound Commands, Parameter Expansion, Word Splitting.
- [bash-handbook](https://github.com/denysdovhan/bash-handbook) — главы про циклы и подстановки.
- [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md)
  — циклы на примерах, по-русски.
- [awesome-bash](https://github.com/awesome-lists/awesome-bash).

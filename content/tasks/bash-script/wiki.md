---
tags: bash, скрипты, аргументы, exit, getopts, бэкап
---
# Свой скрипт: аргументы, ошибки, коды возврата

Скрипт становится настоящей командой, когда ведёт себя как остальные: принимает аргументы,
объясняет, как им пользоваться, пишет ошибки в stderr и отвечает кодом возврата. Тогда его можно
звать из других скриптов, cron и systemd.

## Аргументы

| Переменная | Что в ней |
|---|---|
| `$0` | как вызвали сам скрипт |
| `$1` … `$9`, `${10}` | аргументы по номеру |
| `$#` | сколько аргументов |
| `"$@"` | все, каждый отдельным словом |
| `"$*"` | все одной строкой через пробел |

```
$ cat args.sh
#!/bin/bash
echo "аргументов: $#"
echo "первый: $1"
for a in "$@"; do echo "[$a]"; done
echo "--- без кавычек:"
for a in $@; do echo "[$a]"; done
$ ./args.sh Аня "Боря Петров"
аргументов: 2
первый: Аня
[Аня]
[Боря Петров]
--- без кавычек:
[Аня]
[Боря]
[Петров]
```

`"$@"` в кавычках — единственная форма, которая сохраняет аргументы как есть. `shift` сдвигает
их: `$2` становится `$1`.

## stderr, справка и код возврата

```
$ cat usage.sh
#!/bin/bash
if [ $# -eq 0 ]; then
    echo "Использование: $(basename "$0") файл..." >&2
    exit 1
fi
echo "работаю с $*"
$ ./usage.sh > out.txt; echo код: $?
Использование: usage.sh файл...
код: 1
$ ./usage.sh a.txt b.txt; echo код: $?
работаю с a.txt b.txt
код: 0
```

- `>&2` — в поток ошибок: справка видна, даже когда вывод перенаправлен в файл.
- `exit 0` — успех, `exit 1` (и другие ненулевые) — ошибка. По коду решают `if`, `&&`, cron,
  systemd, CI.
- Ошибка в одном элементе — не всегда повод бросить остальные: `continue` к следующему,
  ошибку запомнить в переменной (`rc=1`) и выйти с ней в конце (`exit $rc`).

## Ключи: getopts

```
$ cat opts.sh
#!/bin/bash
while getopts "d:v" opt; do
    case $opt in
        d) dest=$OPTARG ;;
        v) verbose=1 ;;
        *) echo "Использование: $0 [-v] [-d каталог] файл..." >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))
echo "dest=${dest:-~/backups} verbose=${verbose:-0} файлы: $*"
$ ./opts.sh -v -d /mnt/usb a b
dest=/mnt/usb verbose=1 файлы: a b
$ ./opts.sh -x a
./opts.sh: illegal option -- x
Использование: ./opts.sh [-v] [-d каталог] файл...
```

`d:` — ключ с значением (`$OPTARG`), `v` — флаг. После цикла `shift` убирает ключи, остаются
файлы. `${dest:-~/backups}` — значение по умолчанию.

## Имена с датой и ротация

```
$ basename /home/anya/photos; dirname /home/anya/photos
photos
/home/anya
$ date -d "2026-11-04 15:30:12" +%F_%H%M%S
2026-11-04_153012
```

Формат «от старшего к младшему» (`год-месяц-день_часминсек`) сортируется по алфавиту так же,
как по времени. Поэтому шаблон в массиве сразу даёт архивы от старых к новым:

```
$ logs=(app-*.log); echo ${#logs[@]}; echo "${logs[0]}" "${logs[@]: -1}"; echo "${logs[@]:0:${#logs[@]}-3}"
5
app-2026-01-01.log app-2026-01-05.log
app-2026-01-01.log app-2026-01-02.log
```

Последняя строка — «всё, кроме трёх последних»: кандидаты на удаление.

## Скелет хорошего скрипта

    #!/bin/bash
    set -euo pipefail

    usage() { echo "Использование: $(basename "$0") каталог..." >&2; exit 1; }
    [ $# -gt 0 ] || usage

    rc=0
    for d in "$@"; do
        if [ ! -d "$d" ]; then
            echo "нет каталога: $d" >&2
            rc=2
            continue
        fi
        # работа с "$d"
    done
    exit $rc

## Где это пригодится

- Резервные копии, выгрузки, деплой — всё, что делается чаще двух раз.
- Скрипт с честным кодом возврата можно повесить в cron или службу: при ошибке придёт письмо
  или упадёт сборка, а не пройдёт молча.

## Источники

- [BashGuide: Parameters](https://mywiki.wooledge.org/BashGuide/Parameters) — `$@`, `$#`,
  `shift`.
- [BashFAQ/035: как разбирать ключи и аргументы](https://mywiki.wooledge.org/BashFAQ/035).
- [BashFAQ/028: как скрипту узнать свой каталог](https://mywiki.wooledge.org/BashFAQ/028).
- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), Special
  Parameters, встроенные `getopts`, `exit`, `shift`.
- `man tar` — [на man7.org](https://man7.org/linux/man-pages/man1/tar.1.html).
- [bash-handbook](https://github.com/denysdovhan/bash-handbook),
  [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md),
  [awesome-bash](https://github.com/awesome-lists/awesome-bash).

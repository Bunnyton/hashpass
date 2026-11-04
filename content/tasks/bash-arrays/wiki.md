---
tags: bash, массивы, mapfile, declare, скрипты
---
# Массивы в bash

Переменная хранит одну строку. Список серверов, пользователей, файлов в одну строку через пробел
укладывается, пока в элементах нет пробелов, — а потом всё разваливается. Для списков в bash есть
**массивы**: индексные (ключи 0, 1, 2…) и ассоциативные (ключ — любая строка).

## Индексный массив

```
$ langs=(bash python go); echo ${langs[0]} ${langs[2]} ${#langs[@]}
bash go 3
$ langs+=(rust); echo "${langs[@]}"; echo "${!langs[@]}"; echo ${langs[-1]}
bash python go rust
0 1 2 3
rust
$ echo "${langs[@]:1:2}"
python go
```

| Запись | Что даёт |
|---|---|
| `a=(x y z)` | объявить и заполнить |
| `${a[i]}` | элемент; внутри `[ ]` — арифметика: `${a[i + 1]}`, `${a[i % n]}` |
| `${a[-1]}` | последний |
| `"${a[@]}"` | все элементы, каждый — отдельным словом |
| `${#a[@]}` | сколько элементов |
| `"${!a[@]}"` | все номера (ключи) |
| `"${a[@]:1:2}"` | срез: 2 элемента с номера 1 |
| `a+=(w)` | добавить в конец |
| `unset 'a[1]'` | удалить элемент (номера не сдвигаются!) |
| `declare -p a` | напечатать массив целиком — лучший способ отладки |

После `unset` номера остаются с дырой:

```
$ unset "s[1]"; echo "${!s[@]}"; echo ${#s[@]}
0 2
2
```

Поэтому перебирают через `"${!a[@]}"`, а не `seq 0 $((n-1))`.

## Строки файла — в массив

Ловушка: `$(cat …)` режет по пробелам, а не по строкам:

```
$ a=($(cat servers.txt)); echo ${#a[@]}; declare -p a
6
declare -a a=([0]="web-01" [1]="frontend" [2]="web-02" [3]="frontend" [4]="db-01" [5]="postgres")
$ mapfile -t s < servers.txt; echo ${#s[@]}; declare -p s
3
declare -a s=([0]="web-01 frontend" [1]="web-02 frontend" [2]="db-01 postgres")
```

`mapfile` (он же `readarray`) кладёт по строке в элемент, `-t` срезает перевод строки.

Файлы по шаблону — тоже массив, и имена с пробелами останутся целыми:

```
$ files=(*.txt); echo ${#files[@]} ${files[0]}
1 servers.txt
```

## Кавычки вокруг `${a[@]}`

```
$ for x in ${s[@]}; do echo "[$x]"; done
[web-01]
[frontend]
...
$ for x in "${s[@]}"; do echo "[$x]"; done
[web-01 frontend]
[web-02 frontend]
[db-01 postgres]
```

Без кавычек элементы снова режутся на слова. `"${a[@]}"` — каждый элемент ровно одним словом;
`"${a[*]}"` — все элементы одной строкой через пробел (нужно для `echo`, а не для циклов).

Самое полезное применение — аргументы команды, собранные по частям:

    opts=(-czf backup.tar.gz)
    [ -n "$exclude" ] && opts+=(--exclude "$exclude")
    tar "${opts[@]}" project/

## Ассоциативный массив

Ключ — строка. Объявляется обязательно, через `declare -A`:

```
$ declare -A age; age[Аня]=25; age[Боря]=31; echo ${age[Аня]}; echo "${!age[@]}"
25
Аня Боря
```

Без `declare -A` ключ считается арифметикой:

```
$ n=(); n[203.0.113.5]=1
bash: 203.0.113.5: syntax error: invalid arithmetic operator (error token is ".0.113.5")
```

Подсчёт — главный приём:

```
$ declare -A seen; for w in да нет да да; do seen[$w]=$(( ${seen[$w]:-0} + 1 )); done; declare -p seen
declare -A seen=([да]="3" [нет]="1" )
```

`${seen[$w]:-0}` — значение или 0, если ключа ещё нет. Порядок ключей в `"${!seen[@]}"` не
задан — нужен порядок, отсортируй вывод.

## Поля строки — read

`read` с несколькими переменными раскладывает строку по словам, остаток — в последнюю:

```
$ read -r date time level msg <<< "2026-11-03 10:00:01 WARN диск заполнен"; echo "$level | $msg"
WARN | диск заполнен
```

## Где это пригодится

- Список серверов для обхода: `for host in "${hosts[@]}"; do ssh "$host" uptime; done`.
- Аргументы команды, собранные условиями (`tar`, `rsync`, `curl` с разными ключами).
- Подсчёты по журналам прямо в скрипте, когда `sort | uniq -c` неудобен (нужны несколько
  счётчиков сразу или решение по ходу чтения).
- Массивов нет в `sh` (`dash`): скрипт с массивами начинается с `#!/bin/bash`.

## Источники

- [BashGuide: Arrays](https://mywiki.wooledge.org/BashGuide/Arrays) — Greg's Wiki.
- [BashFAQ/005: как работать с массивами](https://mywiki.wooledge.org/BashFAQ/005).
- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), разделы Arrays
  и `mapfile` в SHELL BUILTIN COMMANDS.
- [bash-handbook](https://github.com/denysdovhan/bash-handbook) — глава «Массивы».
- [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md).
- [awesome-bash](https://github.com/awesome-lists/awesome-bash).

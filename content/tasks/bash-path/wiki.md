---
tags: bash, path, bashrc, source, ссылки
---
# PATH, свой каталог bin и source

Команда в Linux — это файл. Чтобы запустить его по короткому имени, оболочка должна знать, где
искать. Список таких мест — переменная окружения **`PATH`**.

## Как оболочка ищет команду

1. Слово со `/` (`./run.sh`, `/usr/bin/ls`) — это путь: запускается ровно этот файл.
2. Встроенные команды (`cd`, `echo`, `export`, `source`) выполняет сама bash, файла у них нет.
3. Остальное bash ищет в каталогах `PATH` **по порядку**, слева направо, и запускает первый
   найденный исполняемый файл.
4. Не нашла — `command not found`, даже если файл лежит в соседнем каталоге.

```
$ echo $PATH
/usr/bin:/bin
$ type cd ls
cd is a shell builtin
ls is /usr/bin/ls
$ which ls
/usr/bin/ls
```

`type` знает всё, что знает bash (встроенные, псевдонимы, функции), `which` — только файлы в PATH.
Найденный путь bash запоминает (`hash` покажет таблицу); если команду перенесли, `hash -r`
заставит искать заново.

Порядок важен: если в `/usr/local/bin` и `/usr/bin` есть файлы с одним именем, запустится тот,
чей каталог в `PATH` раньше. Так администратор «подменяет» системную программу своей версией, не
трогая пакетную.

## Своя команда через символьную ссылку

Скрипт живёт в проекте, а в каталог из `PATH` кладут только **ссылку** на него:

```
$ ln -s $HOME/projects/hello/hello bin/hello; hello; which hello
Привет из /home/anya/bin/hello
/home/anya/bin/hello
$ readlink -f bin/hello
/home/anya/projects/hello/hello
```

Правишь оригинал — меняется команда. Удалишь оригинал — ссылка повиснет. В консоли задания
ссылка в `/usr/local/bin` выглядит так:

```
$ ls -l /usr/local/bin/todo
lrwxrwxrwx 1 root root 32 Nov  4 02:54 /usr/local/bin/todo -> /home/student/projects/todo/todo
```

**Ловушка — относительная цель.** Цель символьной ссылки читается от каталога, где лежит сама
ссылка, а не от того, где ты был при `ln`:

```
$ ln -s projects/hello/hello bin/hello-rel; ls -l bin
lrwxrwxrwx 1 debi debi 20 Nov  4 02:58 hello-rel -> projects/hello/hello
$ hello-rel
bash: hello-rel: command not found
```

Ссылка ведёт в `bin/projects/hello/hello`, которого нет, — и bash такую ссылку просто не
считает командой. Для ссылок в системные каталоги цель пишут полным путём.

## Целый каталог в PATH

Когда скриптов много, проще добавить в `PATH` их каталог. `PATH` — обычная переменная:

    PATH="$PATH:$HOME/tools/bin"      в конец: системные команды важнее твоих
    PATH="$HOME/tools/bin:$PATH"      в начало: твои важнее системных

**Ловушка — затереть PATH.** Без `$PATH` в значении остаётся один каталог:

```
$ PATH=/nowhere; ls
bash: ls: command not found
```

Починить в этой оболочке: `PATH=/usr/local/bin:/usr/bin:/bin` — или открыть новую.

**Ловушка — тильда в кавычках.** В `"…~/bin"` тильда не раскрывается, в `PATH` попадает буквальный
`~/bin`. bash такую запись всё равно понимает, а другие программы — нет:

```
$ PATH="$PATH:~/bin"; hello; which hello; echo rc=$?
Привет из /home/anya/bin/hello
rc=1
```

Пиши `$HOME` вместо `~`, когда путь в кавычках.

## ~/.bashrc и source

Присваивание `PATH=…` живёт, пока жива оболочка. Чтобы каталог был в каждой новой:

1. Интерактивная bash при старте читает **`~/.bashrc`** и выполняет его строки.
2. Вход в систему (login shell) читает `~/.profile` (или `~/.bash_profile`); в Debian `~/.profile`
   сам добавляет в `PATH` каталоги `~/bin` и `~/.local/bin`, если они есть.
3. Строка в файле не меняет **уже запущенную** оболочку. Её перечитывают командой
   `source ~/.bashrc` (или короче — `. ~/.bashrc`).

Почему не просто запустить файл? Запуск — это дочерний процесс, его `export` до родителя не
доходит. `source` выполняет строки в текущей оболочке:

```
$ echo export NEWVAR=42 > vars.sh
$ bash vars.sh; echo [$NEWVAR]
[]
$ source vars.sh; echo [$NEWVAR]
[42]
```

Так же работают `source venv/bin/activate` у Python и `nvm`.

## Где это пригодится

- Свои утилиты — в `~/bin` или `~/.local/bin`, и они везде под рукой.
- Программа из архива (`/opt/игра/bin`) — каталог в `PATH`, а не копирование в `/usr/bin`.
- «Почему запускается не та версия?» — `type -a имя` покажет все найденные по порядку `PATH`.

## Источники

- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), разделы
  COMMAND EXECUTION (поиск по PATH) и INVOCATION (какие файлы читаются при старте).
- `man 7 environ` — [на man7.org](https://man7.org/linux/man-pages/man7/environ.7.html), про
  `PATH`.
- [PATH (переменная) — Википедия](https://ru.wikipedia.org/wiki/PATH_(переменная)).
- [Environment variables — ArchWiki](https://wiki.archlinux.org/title/Environment_variables) —
  где задавать переменные надолго.
- [bash-handbook](https://github.com/denysdovhan/bash-handbook) и
  [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md).
- [BashGuide (Greg's Wiki)](https://mywiki.wooledge.org/BashGuide).

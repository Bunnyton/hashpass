---
tags: bash, окружение, переменные, export
---
# Переменные окружения

Программе нужно знать, кто её запустил, где его домашний каталог, на каком языке писать ошибки.
Спрашивать каждый раз неудобно, зашивать в код — ещё хуже. Поэтому в Unix у каждого процесса есть
**окружение** — список строк `ИМЯ=значение`, который он получает от родителя при запуске.

## Как это устроено

1. Ты входишь в систему — программа входа задаёт оболочке окружение: `HOME`, `USER`, `PATH`,
   `LANG`, `SHELL`…
2. Оболочка запускает программу — та получает **копию** окружения оболочки.
3. Программа запускает свою — та получает копию копии. И так по всему дереву процессов.
4. Изменить окружение можно только своё и только для будущих детей. Родителю ничего не вернуть.

## Посмотреть

Окружение в чистой оболочке выглядит так (настоящий вывод, пользователь `anya`):

    $ env
    HOME=/home/anya
    LANG=C.UTF-8
    PATH=/usr/bin:/bin
    PWD=/tmp
    SHLVL=1
    USER=anya
    _=/usr/bin/env
    $ printenv HOME
    /home/anya

| Переменная | Что хранит |
|---|---|
| `HOME` | домашний каталог: туда ведёт `cd` без аргументов и `~` |
| `USER`, `LOGNAME` | имя пользователя |
| `PATH` | где искать команды (отдельное задание — bash-path) |
| `LANG`, `LC_*` | язык и формат дат, чисел, сортировки |
| `PWD` | текущий каталог |
| `SHLVL` | на сколько оболочек ты «вложен»: `bash` внутри `bash` — 2 |
| `EDITOR`, `PAGER` | какой редактор и пейджер звать программам (`git`, `crontab -e`) |

## Переменная оболочки и переменная окружения

`ИМЯ=значение` создаёт переменную **внутри оболочки**. `echo $ИМЯ` её видит, а программы — нет:

    $ GREETING=привет
    $ echo $GREETING
    привет
    $ printenv GREETING; echo $?
    1

`printenv` — отдельная программа, она видит только окружение, и там `GREETING` нет (код 1).
`export` переносит переменную в окружение:

    $ export GREETING
    $ printenv GREETING
    привет
    $ bash -c 'echo $GREETING'
    привет

Изменения в дочернем процессе в родителя не возвращаются — даже из подоболочки `( )`:

    $ (export A=5); echo "[$A]"
    []

Поэтому скрипт, который делает `export`, окружение твоей оболочки не меняет. Чтобы скрипт
поменял текущую оболочку, его не запускают, а **читают** в ней: `source файл` (так работают
`~/.bashrc` и `venv/bin/activate` у Python).

## Переменная на одну команду

Запись перед командой даёт переменную только ей; оболочка остаётся прежней:

    $ X=1 bash -c 'echo $X'; echo "[$X]"
    1
    []
    $ LANG=C ls /nope
    ls: cannot access '/nope': No such file or directory

`LANG=C` перед командой — частый приём: сообщения об ошибках по-английски, их проще искать в
интернете. Убрать переменную совсем — `unset ИМЯ`. Запустить с чистым окружением — `env -i
команда`.

## Окружение в разных языках

Окружение даёт ядро при запуске процесса (`execve`), поэтому оно одинаково для всех языков:

| Язык | Прочитать `CITY` |
|---|---|
| C | `getenv("CITY")` |
| Python | `os.environ["CITY"]` или `os.environ.get("CITY")` |
| Node.js | `process.env.CITY` |
| Go | `os.Getenv("CITY")` |
| Java | `System.getenv("CITY")` |
| Perl | `$ENV{CITY}` |

    $ CITY=Казань python3 -c 'import os; print(os.environ["CITY"])'
    Казань
    $ CITY=Казань node -e 'console.log(process.env.CITY)'
    Казань
    $ python3 -c 'import os; print(os.environ["CITY"])'
    KeyError: 'CITY'

Программа `weather` из задания написана на Perl:

    $ CITY=Казань weather
    Казань: +3°C, мокрый снег
    $ weather
    weather: в окружении нет CITY — не знаю, где ты.

## Где это пригодится

- **Настройка без правки кода.** Приложение читает адрес базы и пароль из окружения — один и тот
  же код работает на ноутбуке и на сервере (методология «двенадцати факторов»).
- **Docker и systemd** передают настройки именно так: `docker run -e`, `Environment=` и
  `EnvironmentFile=` в юните (это будет в задании bash-service).
- **Отладка:** `LANG=C команда`, `DEBUG=1 программа`.
- **Секреты:** окружение процесса видно его владельцу и root в `/proc/<PID>/environ` — пароли
  там лучше не держать дольше, чем нужно.

## Источники

- `man 7 environ` — [на man7.org](https://man7.org/linux/man-pages/man7/environ.7.html): что
  такое окружение и какие переменные стандартные.
- `man env` — [на man7.org](https://man7.org/linux/man-pages/man1/env.1.html).
- `man bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html), раздел
  ENVIRONMENT.
- [Environment variables — ArchWiki](https://wiki.archlinux.org/title/Environment_variables) —
  где их задают в системе.
- [Двенадцать факторов: конфигурация](https://12factor.net/ru/config) — почему настройки живут в
  окружении.
- Python [`os.environ`](https://docs.python.org/3/library/os.html), Node.js
  [`process.env`](https://nodejs.org/api/process.html).
- [bash-handbook](https://github.com/denysdovhan/bash-handbook) — короткий учебник bash (есть
  перевод на русский).
- [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md)
  — скрипты на примерах, по-русски.
- [awesome-bash](https://github.com/awesome-lists/awesome-bash) — подборка инструментов и
  материалов по bash.

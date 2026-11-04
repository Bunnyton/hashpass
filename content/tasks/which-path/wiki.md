---
tags: path, which, type, opt, bash, версии
---
# Где лежит программа

Команда в Linux — это файл. Когда ты набираешь имя, оболочка ищет файл с таким именем в каталогах
из переменной `PATH` — **слева направо** — и запускает **первый** найденный:

    $ echo $PATH
    /usr/local/bin:/usr/bin:/bin:/usr/local/games:/usr/games:/usr/local/sbin:/usr/sbin:/sbin

Поэтому `/usr/local/bin` (поставлено руками) стоит раньше `/usr/bin` (из пакетов): своё
перекрывает системное.

## Что запустится: which, type, command -v

    $ which report
    /usr/local/bin/report
    $ type -a report
    report is /opt/acme/report-2.1/bin/report
    report is /usr/local/bin/report

- `which` — отдельная программа, ищет только файлы по PATH; `which -a` — все, а не первый.
- `type` — встроенная команда bash: знает ещё псевдонимы (`alias`), функции и встроенные команды.
  `type -a` показывает всё по порядку — первое и запустится.
- `command -v` — то же в любом POSIX-шелле, удобно в скриптах: `command -v git >/dev/null || echo "нет git"`.

Не в PATH — не значит «нет». Программу можно запустить полным путём, а найти — `find`:

    $ find /opt -name report -type f
    /opt/acme/report-2.1/bin/report
    /opt/acme/report-2.0/bin/report

## /opt и /usr/local

- `/usr/bin` — программы из пакетов; трогает только пакетный менеджер.
- `/usr/local/bin` — то, что админ поставил сам: свои скрипты, собранное из исходников.
- `/opt/<имя>` — стороннее приложение целиком в одном каталоге, со своими `bin/`, `lib/`, `share/`:
  так ставятся браузеры, IDE, агенты мониторинга. В PATH их каталог обычно не входит.

Поэтому несколько версий одной программы — обычное дело: системная и новая из `/opt`, python
из пакета и из pyenv, java 17 и 21.

## Как выбрать версию

1. **Поменять PATH** — поставить нужный каталог в начало:

        export PATH=/opt/acme/report-2.1/bin:$PATH

   `export` живёт до выхода из оболочки. Навсегда — та же строка в `~/.bashrc` (для всех — файл в
   `/etc/profile.d/`).
2. **Ссылка** в каталог, который в PATH уже есть: `sudo ln -s /opt/acme/report-2.1/bin/report
   /usr/local/bin/report` — для всех пользователей сразу.
3. **Псевдоним** `alias report=/opt/acme/report-2.1/bin/report` — только для интерактивной оболочки;
   скрипты его не видят.
4. **Альтернативы Debian** — `update-alternatives` переключает системные `editor`, `java`, `python`
   ссылками в `/etc/alternatives/`.

## bash помнит, где что нашёл

Обходить PATH на каждую команду долго, поэтому bash запоминает найденное:

    $ hash
    hits	command
       1	/usr/local/bin/report

Убрал или переложил файл — bash по старой памяти идёт туда же и получает «No such file or
directory». `hash -r` — забыть всё, `hash -d report` — забыть одно. Новая оболочка начинает с
пустой памятью; присваивание `PATH=…` тоже её сбрасывает.

## Источники

- `man 1 bash` — [на man7.org](https://man7.org/linux/man-pages/man1/bash.1.html): разделы COMMAND EXECUTION (порядок поиска), `type`, `hash`.
- `man 7 environ` — [на man7.org](https://man7.org/linux/man-pages/man7/environ.7.html): переменная PATH.
- `man 7 hier` — [на man7.org](https://man7.org/linux/man-pages/man7/hier.7.html): /opt, /usr/local.
- [Filesystem Hierarchy Standard 3.0](https://refspecs.linuxfoundation.org/FHS_3.0/fhs/index.html) — для чего /opt.

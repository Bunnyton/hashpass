---
tags: apt, репозиторий, пакеты, gpg
---
# Сторонние репозитории apt

apt ставит только то, о чём знает, а знает он только записанные у него репозитории. Чего нет
в Debian (или есть, но старое), то производители держат в **своих** репозиториях: Docker,
Google Chrome, VS Code, Яндекс Браузер, Node.js. Подключил такой — и программа ставится и
обновляется обычным `apt`, вместе со всей системой. Основы apt — в
[wiki про apt](/web/wiki/bunnyton/apt-update).

## Когда пакета нет

    $ apt-get -s install no-such-pkg
    Reading state information...
    E: Unable to locate package no-such-pkg

`Unable to locate package` — имени нет ни в одном известном списке. Бывает ещё
`has no installation candidate`: имя apt слышал (кто-то на него ссылается), а скачать нечего.
Оба значат одно — опечатка или пакет живёт в другом репозитории.

## Где записаны репозитории

Основной список — `/etc/apt/sources.list` (или `debian.sources`), подключённые позже —
отдельными файлами в `/etc/apt/sources.list.d/`, по файлу на репозиторий. Однострочный формат:

    $ cat /etc/apt/sources.list.d/yarn.list
    deb [signed-by=/etc/apt/trusted.gpg.d/yarn.gpg] https://dl.yarnpkg.com/debian/ stable main

По частям: `deb` — готовые пакеты; в `[ ]` — параметры (`arch=` архитектура, `signed-by=`
ключ); адрес; **дистрибутив** (`stable`, `trixie`, `bookworm`…); **разделы** (`main`…).

Новый формат deb822 (`.sources`) — то же самое, но поле на строку:

    $ cat /etc/apt/sources.list.d/yandex-browser.sources
    ...
    Types: deb
    URIs: https://repo.yandex.ru/yandex-browser/deb/
    Suites: stable
    Components: main
    Architectures: amd64
    Signed-By: /usr/share/keyrings/yandex-browser.gpg

## Зачем ключ

Любой может поднять сервер с пакетом `chrome`. Поэтому производитель **подписывает** списки
пакетов своим ключом, а apt проверяет подпись открытым ключом, который ты положил заранее.
Ключи обычно кладут в `/etc/apt/keyrings/` или `/usr/share/keyrings/`:

    $ file /usr/share/keyrings/yandex-browser.gpg
    /usr/share/keyrings/yandex-browser.gpg: OpenPGP Public Key Version 4, Created Tue May 16 16:15:58 2023, RSA (Encrypt or Sign, 4096 bits); User ID; Signature; OpenPGP Certificate

`.gpg` — ключ в двоичном виде, `.asc` — тот же ключ текстом (начинается со строки
`-----BEGIN PGP PUBLIC KEY BLOCK-----`); apt понимает оба. Ключа нет или
он не тот — `apt update` ругнётся `NO_PUBKEY` и этот репозиторий читать не будет.
`signed-by` привязывает ключ к **одному** репозиторию: так чужой ключ не сможет подписывать
пакеты Debian.

## Кирпичики из инструкций производителей

Инструкции по подключению почти всегда собраны из трёх приёмов bash.

**`$( … )` — подставить вывод команды.** Так запись сама узнаёт архитектуру и версию системы:

    $ dpkg --print-architecture
    amd64
    $ . /etc/os-release && echo "$VERSION_CODENAME"
    trixie
    $ echo "сегодня $(date +%A)"
    сегодня Wednesday

**`\` в конце строки** — команда продолжается на следующей строке; это всё ещё одна команда.

**`| sudo tee файл`** — записать в файл, куда у тебя нет прав. `sudo echo … > файл` не
сработает: `>` делает твоя оболочка, без прав, и `sudo` до неё не дотягивается. `tee`
пишет пришедшее по конвейеру в файл и заодно на экран; лишнюю копию прячут `> /dev/null`:

    $ echo test | tee note.txt > /dev/null
    $ cat note.txt
    test

## После подключения: откуда пакет

После `apt update` новый репозиторий появляется в `apt-cache policy` — видно, какая версия
откуда придёт:

    $ apt-cache policy yarn
    yarn:
      Installed: (none)
      Candidate: 1.22.22-1
      Version table:
         1.22.22-1 500
            500 https://dl.yarnpkg.com/debian stable/main amd64 Packages
            500 https://dl.yarnpkg.com/debian stable/main all Packages
    ...

Число `500` — приоритет: если пакет есть в нескольких репозиториях, apt берёт самую свежую
версию среди равных по приоритету.

## Осторожно

- репозиторий получает право ставить в систему что угодно от root — подключай только
  официальные, по инструкции с сайта производителя;
- не смешивай дистрибутивы: репозиторий для Ubuntu или для `bookworm` в `trixie` легко
  сломает зависимости;
- отключить репозиторий — удалить его файл из `sources.list.d` (и ключ) и снова `apt update`.

## Источники

- [sources.list(5) по-русски — manpages.debian.org](https://manpages.debian.org/trixie/apt/sources.list.5.ru.html)
  — оба формата записей.
- [SourcesList — Debian Wiki](https://wiki.debian.org/SourcesList)
- [Сторонние репозитории — Debian Wiki](https://wiki.debian.org/DebianRepository/UseThirdParty)
  — как правильно подключать ключи и `signed-by`.
- [Install Docker Engine on Debian](https://docs.docker.com/engine/install/debian/) — пример
  официальной инструкции производителя.

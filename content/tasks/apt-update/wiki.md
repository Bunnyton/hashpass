---
tags: apt, пакеты, debian, установка
---
# apt: откуда берутся программы

В Debian программы не качают с сайтов по одной — их ставит **пакетный менеджер** `apt`.
Он знает, где лежат тысячи программ, скачивает нужную вместе со всем, без чего она не
работает, и потом умеет её обновить и удалить. Все команды кратко — в
[шпаргалке](wiki/cheatsheet.md).

## Пакет и репозиторий

**Пакет** — архив `.deb`: файлы программы, описание и список **зависимостей** — других
пакетов, которые нужны ей для работы. **Репозиторий** — сервер, где лежат пакеты и общий
список: что есть, какой версии, от чего зависит. Адреса репозиториев apt берёт из настроек:

    $ grep '^deb ' /etc/apt/sources.list
    deb http://deb.debian.org/debian/ trixie main non-free-firmware
    deb http://security.debian.org/debian-security trixie-security main non-free-firmware
    deb http://deb.debian.org/debian/ trixie-updates main non-free-firmware

(строки `deb` — откуда брать готовые пакеты; ещё там бывают `deb-src` — исходники. В новых системах тот же список лежит в
`/etc/apt/sources.list.d/debian.sources`). Подробнее про записи — в
[wiki про сторонние репозитории](/web/wiki/bunnyton/apt-add-repo).

## apt знает только то, что скачал в прошлый раз

Списки пакетов apt хранит у себя на диске и сам по себе их не обновляет. Посмотри на даты:

    $ date
    Wed Nov  4 02:26:47 AM MSK 2026
    $ ls -l --time-style=long-iso /var/lib/apt/lists/*InRelease | head -2
    -rw-r--r-- 1 root root 140421 2026-09-12 10:59 /var/lib/apt/lists/deb.debian.org_debian_dists_trixie_InRelease
    -rw-r--r-- 1 root root  47340 2026-10-31 23:14 /var/lib/apt/lists/deb.debian.org_debian_dists_trixie-updates_InRelease

Основной список здесь — двухмесячной давности. Всё, что вышло позже, apt просто не видит
и поставит то, что было свежим тогда. `apt update` скачивает свежие списки со всех
репозиториев — и только: сами программы он не трогает.

Не путай:

- `apt update` — обновить **списки** («что нового в репозиториях»);
- `apt upgrade` — обновить **установленные программы** до версий из списков.

Поэтому обычный порядок — сначала `update`, потом `install` или `upgrade`.

## Что есть и какой версии

Ни одна из этих команд не требует root — смотреть можно сколько угодно:

    $ apt search --names-only '^cowsay'
    Sorting...
    Full Text Search...
    cowsay/stable 3.03+dfsg2-8 all
      configurable talking cow

    cowsay-off/stable 3.03+dfsg2-8 all
      configurable talking cow (offensive cows)

    $ apt list cowsay openssl
    Listing...
    cowsay/stable 3.03+dfsg2-8 all
    openssl/stable-security 3.5.7-1~deb13u3 amd64 [upgradable from: 3.5.7-1~deb13u2]

`apt show пакет` — описание, размер, зависимости. А `apt-cache policy` отвечает на главный
вопрос: что стоит и что поставится:

    $ apt-cache policy openssl
    openssl:
      Installed: 3.5.7-1~deb13u2
      Candidate: 3.5.7-1~deb13u3
      Version table:
         3.5.7-1~deb13u3 500
            500 http://security.debian.org/debian-security trixie-security/main amd64 Packages
     *** 3.5.7-1~deb13u2 500
            500 http://deb.debian.org/debian trixie/main amd64 Packages
            100 /var/lib/dpkg/status

`Installed` — что стоит сейчас, `Candidate` — что поставит `apt install`, `***` — текущая
версия. Свежую версию из `trixie-security` apt увидел только потому, что списки обновлялись.

## Установка требует root

Ставить и удалять программы — менять систему, поэтому без `sudo` apt откажет сразу:

    $ apt update
    Error: Could not open lock file /var/lib/apt/lists/lock - open (13: Permission denied)
    Error: Unable to lock directory /var/lib/apt/lists/
    $ apt install cowsay
    Error: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)
    Error: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), are you root?

Про `sudo` — в [отдельной wiki](/web/wiki/bunnyton/sudo-basics). Посмотреть, что сделала бы
установка, можно и без прав — ключ `-s` (simulate) у `apt-get`:

    $ apt-get -s install cowsay
    NOTE: This is only a simulation!
          apt-get needs root privileges for real execution.
    ...
    The following NEW packages will be installed:
      cowsay
    0 upgraded, 1 newly installed, 0 to remove and 255 not upgraded.
    Inst cowsay (3.03+dfsg2-8 Debian:13.7/stable [all])
    Conf cowsay (3.03+dfsg2-8 Debian:13.7/stable [all])

## apt и apt-get

`apt` — новая команда для людей: прогресс-бар, цвета, короткие слова. `apt-get` и
`apt-cache` — старые, со стабильным выводом, их пишут в скриптах и Dockerfile. Действия
у них одни и те же: `apt install` = `apt-get install`, `apt show` = `apt-cache show`.

## Где после установки программа

Обычно в `/usr/bin`. Игрушки Debian кладёт в `/usr/games` — этот каталог тоже есть в `PATH`,
поэтому запускаются они просто по имени. Где именно лежит команда — `command -v имя`.

## Источники

- [apt(8) по-русски — manpages.debian.org](https://manpages.debian.org/trixie/apt/apt.8.ru.html)
- [apt-get(8) по-русски](https://manpages.debian.org/trixie/apt/apt-get.8.ru.html) — все
  действия и ключи, включая `-s`.
- [Apt — Debian Wiki (русский)](https://wiki.debian.org/ru/Apt)
- [Debian Handbook: apt-get и apt](https://www.debian.org/doc/manuals/debian-handbook/sect.apt-get.ru.html)
  — подробно и по-русски.
- [Advanced Packaging Tool — Википедия](https://ru.wikipedia.org/wiki/Advanced_Packaging_Tool)

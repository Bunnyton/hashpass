---
tags: apt, пакеты, удаление, dpkg
---
# Удаление пакетов: remove, purge, autoremove

Поставить пакет — полдела. Рано или поздно его захочется убрать, и тут у apt три разных
действия: убрать программу, убрать программу вместе с настройками, подчистить то, что
ставилось только ради неё. Основы apt — в [wiki про apt](/web/wiki/bunnyton/apt-update).

Все примеры ниже — симуляция (`apt-get -s`): видно, что сделал бы apt, а система не меняется
и root не нужен. По-настоящему те же действия выполняют через `sudo` без `-s`.

## remove — убрать программу

    $ apt-get -s remove lynx
    ...
    0 upgraded, 0 newly installed, 1 to remove and 255 not upgraded.
    Remv lynx [2.9.2-1]

Программа уходит, а её **файлы настроек** (conffiles — обычно в `/etc`) остаются. Это
нарочно: поставишь снова — всё, что ты в ней настраивал, будет на месте. Какие файлы пакет
считает своими настройками, знает dpkg:

    $ dpkg-query -W -f='${Conffiles}\n' lynx-common
     /etc/lynx/lynx.cfg ef263b1765714962fc583cb5d441de18
     /etc/lynx/lynx.lss 38cb5a12468abaa8f99804534fe38ca9

## Состояние rc: программы нет, настройки остались

`dpkg -l` показывает состояние двумя буквами: первая — чего хотели, вторая — что есть.

    $ dpkg -l hashpass lynx | tail -2
    rc  hashpass       2.0          amd64        hashpass
    ii  lynx           2.9.2-1      amd64        classic non-graphical (text-mode) web browser

`ii` — установлен. `rc` — удалён (**r**emove), но **c**onfig-файлы остались. Все такие
хвосты в системе: `dpkg -l | grep '^rc'`.

## purge — вместе с настройками

    $ apt-get -s purge lynx
    ...
    Purg lynx [2.9.2-1]

`purge` = `remove` + файлы настроек. Работает и после `remove`: пакет в состоянии `rc`
вычищается до конца и из `dpkg -l` пропадает. Удалять настройки руками (`rm` в `/etc`) —
плохая идея: у пакета их бывает много и в разных местах, а dpkg знает их все. Учти: purge
не трогает то, что программа создала в твоём домашнем каталоге (`~/.config/…`, `~/.имя`), —
это уже твои файлы, не пакета.

## autoremove — лишние зависимости

Когда ты ставишь пакет, apt приносит и его зависимости — и помечает их «поставлены
автоматически». Сам ты их не просил, поэтому, когда последний пакет, которому они были
нужны, удалён, они становятся мусором. apt сам напоминает об этом при каждом удалении:

    The following packages were automatically installed and are no longer required:
      ca-certificates-mono cli-common gir1.2-adw-1 ...
    Use 'apt autoremove' to remove them.

Кто поставлен автоматически, кто вручную — `apt-mark`:

    $ apt-mark showauto lynx-common libncursesw6
    lynx-common
    $ apt-cache rdepends --installed lynx-common
    lynx-common
    Reverse Depends:
      lynx

`lynx-common` — автоматический и нужен только `lynx`. Уйдёт `lynx` — `lynx-common`
попадёт в список autoremove. А `libncursesw6` не в списке автоматических — её никто не
уберёт. Если зависимость нужна тебе самому, `apt-mark manual пакет` защитит её от
autoremove.

Всё одной командой — `--autoremove` к remove или purge:

    $ apt-get -s purge --autoremove lynx | grep lynx
      libpeas-2-common* libslirp0* lynx* lynx-common* mailcap* mono-4.0-gac*
    Purg lynx [2.9.2-1]
    Purg lynx-common [2.9.2-1]

Звёздочка после имени — пакет уйдёт вместе с настройками.

## Прежде чем нажать Y

apt всегда показывает список перед удалением — **читай его**. Удаление одного пакета может
потянуть за собой другие, которые от него зависят: снеся что-то базовое, можно остаться
без рабочего стола. Если в списке неожиданно много — отвечай `n` и сначала проверь через `-s`.

## Источники

- [apt(8) по-русски](https://manpages.debian.org/trixie/apt/apt.8.ru.html) — remove, purge,
  autoremove.
- [apt-mark(8) по-русски](https://manpages.debian.org/trixie/apt/apt-mark.8.ru.html) —
  автоматические и ручные пакеты.
- [dpkg-query(1) по-русски](https://manpages.debian.org/trixie/dpkg/dpkg-query.1.ru.html) —
  что значат буквы состояния в `dpkg -l`.
- [Debian Handbook: apt-get и apt](https://www.debian.org/doc/manuals/debian-handbook/sect.apt-get.ru.html)

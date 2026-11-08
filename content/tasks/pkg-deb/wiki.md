---
tags: пакеты, deb, dpkg-deb, apt, control
---
# .deb своими руками

`.deb` — архив `ar` из трёх частей: `debian-binary` (версия формата), `control.tar` (паспорт и
скрипты) и `data.tar` (файлы, которые лягут в систему).

    $ ar t hello-cat_0.3_all.deb
    debian-binary
    control.tar.xz
    data.tar.xz

## Собрать

Каталог повторяет корень системы, паспорт — в `DEBIAN/control`:

    hello-cat/DEBIAN/control
    hello-cat/usr/bin/hello-cat
    hello-cat/usr/share/man/man1/hello-cat.1.gz

    $ dpkg-deb --root-owner-group --build hello-cat hello-cat_0.3_all.deb

## Поля control

| Поле | Пример |
|---|---|
| `Package` | `hello-cat` |
| `Version` | `0.3`, `1.2.0-1`, `2:1.0` (эпоха) |
| `Architecture` | `all`, `amd64`, `arm64` |
| `Maintainer` | `Вася Пупкин <vasya@example.com>` |
| `Depends` | `figlet, curl (>= 7.0) \| wget` |
| `Recommends`, `Suggests` | ставятся по умолчанию / только по желанию |
| `Description` | первая строка — кратко, ниже — с пробелом в начале |

Скрипты `preinst`, `postinst`, `prerm`, `postrm` в `DEBIAN/` выполняются при установке и
удалении (создать пользователя, перезапустить службу).

## Посмотреть и поставить

    $ dpkg-deb -I файл.deb        # паспорт
    $ dpkg-deb -c файл.deb        # список файлов
    $ sudo apt install ./файл.deb  # поставить и дотянуть Depends из репозитория
    $ dpkg -L hello-cat           # что пакет положил в систему
    $ dpkg --compare-versions 1.10 gt 1.9 && echo да

`dpkg -i` ставит только сам файл: при нехватке зависимостей пакет останется ненастроенным.

## Источники

- [Debian Policy: Control files](https://www.debian.org/doc/debian-policy/ch-controlfields.html)
- [dpkg-deb(1)](https://manpages.debian.org/trixie/dpkg/dpkg-deb.1.en.html), [deb(5)](https://manpages.debian.org/trixie/dpkg-dev/deb.5.en.html)

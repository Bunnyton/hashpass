---
tags: пакеты, debian, debhelper, dpkg-buildpackage, lintian
---
# Исходный пакет Debian

Так собраны все пакеты Debian и Ubuntu: исходники + каталог `debian/`, сборка —
`dpkg-buildpackage`, правила — `debhelper` (`dh`).

    debian/
    ├── changelog      версия и история (dch)
    ├── control        паспорт исходников и бинарных пакетов
    ├── copyright      лицензия (машиночитаемый формат)
    ├── rules          исполняемый Makefile: обычно три строки с dh
    └── source/format  3.0 (native) или 3.0 (quilt)

## rules и override

    #!/usr/bin/make -f
    %:
    	dh $@

    override_dh_auto_install:
    	$(MAKE) install DESTDIR=$(CURDIR)/debian/hello-cat PREFIX=/usr

`dh` прогоняет шаги `dh_auto_configure`, `dh_auto_build`, `dh_auto_test`, `dh_auto_install`,
`dh_installdocs`, `dh_strip`, `dh_gencontrol`, … Любой можно заменить целью `override_<шаг>`.

## Форматы исходников

| Формат | Когда |
|---|---|
| `3.0 (native)` | программа и упаковка — одно целое (версия без `-1`) |
| `3.0 (quilt)` | чужая программа: оригинальный `имя_версия.orig.tar.gz` + `debian/` + патчи в `debian/patches` |

## Команды

    $ dch --create --package hello-cat -v 0.3 "Первый выпуск."
    $ dch -v 0.4 "Котик стал пушистее."
    $ dpkg-buildpackage -us -uc        # без подписи; результат — уровнем выше
    $ lintian ../hello-cat_0.4_all.deb  # E — ошибка, W — предупреждение
    $ lintian -i …                      # с объяснениями

Для сборки в чистом окружении используют `sbuild` или `pbuilder`: они ставят только
Build-Depends и ловят забытые зависимости.

## Источники

- [Debian New Maintainers' Guide](https://www.debian.org/doc/manuals/maint-guide/)
- [debhelper(7)](https://manpages.debian.org/trixie/debhelper/debhelper.7.en.html), [dh(1)](https://manpages.debian.org/trixie/debhelper/dh.1.en.html)
- [Lintian tags](https://udd.debian.org/lintian-tags/)

# /usr/local — не для пакетов

`/usr/local` в Debian принадлежит администратору: туда ставят руками, а пакетам туда нельзя —
`dh_usrlocal` это и проверяет. А `Makefile` pelmeni по умолчанию ставит именно туда
(`PREFIX ?= /usr/local`).

Любой шаг `dh` можно заменить своим — целью `override_<шаг>` в `rules`:

```make
override_dh_auto_install:
	$(MAKE) install DESTDIR=$(CURDIR)/debian/hello-cat PREFIX=/usr
```

`DESTDIR` — куда «ставить» при сборке: `debian/<пакет>/` и станет содержимым пакета.

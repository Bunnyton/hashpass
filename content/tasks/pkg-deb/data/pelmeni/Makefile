PREFIX ?= /usr/local
DESTDIR ?=

all:
	@echo "собирать нечего: pelmeni — скрипт. Дальше: make install"

install:
	install -Dm755 pelmeni $(DESTDIR)$(PREFIX)/bin/pelmeni
	install -Dm644 pelmeni.1 $(DESTDIR)$(PREFIX)/share/man/man1/pelmeni.1
	install -Dm644 pelmeni.desktop $(DESTDIR)$(PREFIX)/share/applications/pelmeni.desktop
	install -Dm644 pelmeni.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/pelmeni.svg

.PHONY: all install

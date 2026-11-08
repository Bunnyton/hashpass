# Пакеты: исходный пакет Debian

Каталог debian/ (control, rules с dh, changelog через dch, source/format) и dpkg-buildpackage.
Ловушки — подпись (-us -uc) и dh_usrlocal: Makefile ставит в /usr/local, нужен
override_dh_auto_install. Потом версия 1.1 через dch и чистый lintian (debian/copyright).

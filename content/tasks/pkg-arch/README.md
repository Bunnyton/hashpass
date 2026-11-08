# Пакеты: Arch Linux

PKGBUILD и makepkg: тарбол рядом, контрольные суммы через makepkg -g, package() с DESTDIR.
Потом depends=(figlet) и pkgrel=2 — makepkg хочет проверить зависимости через pacman, которого
в Debian нет (-d).

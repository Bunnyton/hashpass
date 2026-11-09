# Пакеты: Arch Linux

PKGBUILD и makepkg: тарбол рядом, контрольные суммы через makepkg -g, package() с DESTDIR.
Потом depends=(figlet) и pkgrel=2 — makepkg проверяет зависимости по базе pacman, а она здесь
пустая (-d). В конце свой пакет ставит pacman -U, как в настоящем Arch.

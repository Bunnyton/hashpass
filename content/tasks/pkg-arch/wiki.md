---
tags: пакеты, arch, pkgbuild, makepkg, pacman
---
# PKGBUILD и makepkg

В Arch Linux рецепт — bash-скрипт `PKGBUILD`, сборка — `makepkg` (всегда не от root),
установка — `pacman -U`. Так же собирается всё в AUR — пользовательском репозитории Arch.

    pkgname=hello-cat
    pkgver=0.3
    pkgrel=1
    pkgdesc="Печатает котика"
    arch=('any')
    url="https://example.com/hello-cat"
    license=('MIT')
    depends=('figlet')
    makedepends=('make')
    source=("https://example.com/$pkgname-$pkgver.tar.gz")
    sha256sums=('…')

    build() {
        cd "$pkgname-$pkgver"
        make
    }

    package() {
        cd "$pkgname-$pkgver"
        make DESTDIR="$pkgdir" PREFIX=/usr install
    }

| Переменная/функция | Смысл |
|---|---|
| `pkgver` / `pkgrel` | версия программы / номер сборки пакета этой версии |
| `source`, `sha256sums` | откуда брать и чем проверять |
| `prepare()`, `build()`, `check()`, `package()` | шаги; `package()` обязателен |
| `$srcdir`, `$pkgdir` | где распакованы исходники / корень будущего пакета |

## Команды

    $ makepkg -g >> PKGBUILD    # посчитать суммы (на Arch удобнее updpkgsums)
    $ makepkg                   # собрать
    $ makepkg -si               # собрать, поставить зависимости и сам пакет
    $ makepkg -d                # не проверять зависимости
    $ makepkg -f                # пересобрать, хотя пакет уже есть
    $ sudo pacman -U файл.pkg.tar.zst
    $ bsdtar -xOf файл.pkg.tar.zst .PKGINFO

## Источники

- [ArchWiki: PKGBUILD](https://wiki.archlinux.org/title/PKGBUILD)
- [ArchWiki: Creating packages](https://wiki.archlinux.org/title/Creating_packages)
- [makepkg(8)](https://man.archlinux.org/man/makepkg.8)

# PKGBUILD

В Arch Linux рецепт пакета — **PKGBUILD**: обычный bash-скрипт с переменными и функциями.
Собирает `makepkg` — в том каталоге, где лежит PKGBUILD. Пример для `hello-cat`:

```bash
pkgname=hello-cat
pkgver=0.3
pkgrel=1
pkgdesc="Печатает котика"
arch=('any')
license=('MIT')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('…')

package() {
    cd "$pkgname-$pkgver"
    install -Dm755 hello-cat "$pkgdir/usr/bin/hello-cat"
}
```

- `source` — откуда брать исходники: ссылка или файл рядом с PKGBUILD. `makepkg` сам
  распакует архив.
- `package()` — разложить файлы в `$pkgdir` — будущий корень пакета.
- `arch=('any')` — для любого процессора (скрипт).

Результат — `имя-версия-релиз-архитектура.pkg.tar.<сжатие>` рядом с PKGBUILD: на Arch это
`.zst`, а здешний `makepkg` по своим настройкам жмёт в `.gz`.

`makepkg` и `pacman` есть и в Debian: собирать пакеты для Arch можно где угодно, а ставить их
здесь некуда — системой правит `apt`. Исходники pelmeni — в `~/pelmeni`, и в нём есть `Makefile` с целью `install`.

# Исходный пакет Debian

Пакеты Debian собирают не из готового дерева, а из **исходников**: рядом с ними кладут
каталог `debian/` — рецепт сборки, — и команда `dpkg-buildpackage` сама собирает, раскладывает
и упаковывает. Так собрано всё в репозиториях Debian и Ubuntu.

Минимальный `debian/`:

| Файл | Что в нём |
|---|---|
| `control` | паспорт исходников и пакетов, которые из них получаются |
| `rules` | как собрать: исполняемый Makefile |
| `changelog` | история версий — отсюда берётся версия пакета |
| `source/format` | формат исходников: `3.0 (native)` — программа и упаковка живут вместе |

`control` из двух абзацев — для исходников и для пакета:

```
Source: hello-cat
Section: utils
Priority: optional
Maintainer: Вася Пупкин <vasya@example.com>
Build-Depends: debhelper-compat (= 13)
Standards-Version: 4.7.0

Package: hello-cat
Architecture: all
Depends: ${misc:Depends}
Description: печатает котика
 Длинное описание — со следующей строки, с пробелом в начале.
```

`rules` почти всегда одинаковый: всю работу делает **debhelper** (`dh`) — он сам позовёт
`make`, `make install` и разложит файлы по пакету:

```make
#!/usr/bin/make -f
%:
	dh $@
```

Сборка — из каталога исходников: `dpkg-buildpackage`. Готовый `.deb` появится уровнем выше.

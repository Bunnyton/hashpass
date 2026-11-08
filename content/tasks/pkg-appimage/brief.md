# AppImage

`.deb` ставится в Debian и Ubuntu, `.rpm` — в Fedora. **AppImage** — один исполняемый файл,
который запускается на любом Linux без установки: скачал, дал право на запуск — работает.
Так раздают Krita, Inkscape, Obsidian.

Внутри AppImage — сжатый каталог **AppDir** и маленький загрузчик. AppDir устроен так
(пример — `HelloCat.AppDir`):

```
HelloCat.AppDir/
├── AppRun              ← что запустить: скрипт или ссылка на программу
├── hello-cat.desktop   ← описание для меню: имя, иконка, категория
├── hello-cat.svg       ← иконка (имя — из строки Icon= в .desktop)
└── usr/
    └── bin/
        └── hello-cat
```

`AppRun` запускается первым. Обычно это скрипт, который находит себя и запускает программу:

```sh
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
exec "$HERE/usr/bin/hello-cat" "$@"
```

Упаковывает AppDir `appimagetool` (здесь он уже установлен):

```sh
appimagetool HelloCat.AppDir
```

Исходники pelmeni — в `~/pelmeni`, вместе с `.desktop` и иконкой.

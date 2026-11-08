---
tags: пакеты, appimage, appdir, appimagetool, fuse
---
# AppImage

Один исполняемый файл на любой Linux: внутри — загрузчик (runtime) и сжатый squashfs-образ
каталога **AppDir**. При запуске runtime монтирует образ через FUSE и запускает `AppRun`.

    Hello.AppDir/
    ├── AppRun                 точка входа
    ├── hello-cat.desktop      Name=, Exec=, Icon=, Categories=
    ├── hello-cat.svg          иконка (имя — из Icon=)
    └── usr/                   программа и всё, что ей нужно

`AppRun` обычно — скрипт, который находит себя и готовит окружение:

    #!/bin/sh
    HERE=$(dirname "$(readlink -f "$0")")
    export PATH="$HERE/usr/bin:$PATH"
    export LD_LIBRARY_PATH="$HERE/usr/lib:$LD_LIBRARY_PATH"
    exec "$HERE/usr/bin/hello-cat" "$@"

## Команды

    $ appimagetool Hello.AppDir                 # → Hello-x86_64.AppImage
    $ chmod +x Hello-x86_64.AppImage && ./Hello-x86_64.AppImage
    $ ./Hello-x86_64.AppImage --appimage-extract       # распаковать в squashfs-root/
    $ ./Hello-x86_64.AppImage --appimage-extract-and-run   # без FUSE

Нет FUSE (контейнеры, старые системы) — `--appimage-extract-and-run` или переменная
`APPIMAGE_EXTRACT_AND_RUN=1`.

## Зависимости — внутрь

AppImage ничего не ставит в систему. Библиотеки и программы кладут в AppDir: руками (`apt-get
download` + `dpkg -x`) или инструментами `linuxdeploy`, `appimage-builder`. Правило — собирать на
самой старой системе, где программа должна работать: glibc внутри не кладут, она берётся из
системы.

## Источники

- [AppImage documentation](https://docs.appimage.org/)
- [appimagetool](https://github.com/AppImage/appimagetool)

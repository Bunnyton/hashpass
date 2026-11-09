---
tags: пакеты, flatpak, flathub, ostree, песочница
---
# flatpak

flatpak — приложения, которые работают в песочнице (bubblewrap) поверх общего **runtime**. Ставят
их из репозиториев, главный — [Flathub](https://flathub.org). Хранит всё `ostree` — «git для
файловых систем»: одинаковые файлы у разных приложений и версий лежат на диске один раз.

    $ flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    $ flatpak install flathub org.telegram.desktop
    $ flatpak run org.telegram.desktop
    $ flatpak list --app
    $ flatpak update

| Понятие | Смысл |
|---|---|
| ID приложения | перевёрнутый домен: `org.gimp.GIMP` |
| runtime | общая основа: `org.freedesktop.Platform`, `org.gnome.Platform`, `org.kde.Platform` |
| SDK | runtime + компиляторы — на нём собирают |
| `/app` | файлы приложения внутри песочницы (`files/` в его каталоге) |
| `metadata` | паспорт: имя, runtime, команда, права, переменные |
| бандл `.flatpak` | приложение одним файлом, без репозитория |

## Манифест flatpak-builder

Так приложения собирают на самом деле — одним рецептом:

    id: org.hashpass.Pelmeni
    runtime: org.freedesktop.Platform
    runtime-version: '24.08'
    sdk: org.freedesktop.Sdk
    command: pelmeni
    finish-args:
      - --env=FIGLET_FONTDIR=/app/share/figlet
    modules:
      - name: figlet
        buildsystem: simple
        build-commands:
          - make install prefix=/app
        sources:
          - type: archive
            url: https://github.com/cmatsuoka/figlet/archive/refs/tags/2.2.5.tar.gz
            sha256: …
      - name: pelmeni
        buildsystem: simple
        build-commands:
          - make install PREFIX=/app
        sources:
          - type: dir
            path: pelmeni

    $ flatpak-builder --user --install build org.hashpass.Pelmeni.yml

Каждый модуль собирается в песочнице на SDK и ставится в `/app`; `finish-args` — то же, что ключи
`build-finish`.

## Права песочницы

По умолчанию приложение не видит ни дом, ни сеть. Разрешения — в `finish-args`:
`--share=network`, `--filesystem=home`, `--socket=wayland`, `--device=dri`. Посмотреть и
поменять у установленного: `flatpak info --show-permissions <id>`, `flatpak override`, или
программа Flatseal.

## snap или flatpak

Оба несут всё своё и работают в коробке. snap — от Canonical, один магазин, умеет и серверные
службы; flatpak — только приложения для рабочего стола, репозиториев сколько угодно, общие
runtime вместо `base`.

## Источники

- [docs.flatpak.org](https://docs.flatpak.org/) — документация, в том числе flatpak-builder
- [man flatpak-build-bundle](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)

---
tags: пакеты, snap, snapcraft, snapd, squashfs
---
# snap

Снап — squashfs-образ с программой и всем, что ей нужно, плюс паспорт `meta/snap.yaml`.
Ставит и обновляет `snapd`; каждый снап работает в своей коробке (AppArmor, seccomp), а
наружу ходит только через **интерфейсы** (`plugs`).

    name: hello-cat
    version: '0.3'
    summary: Печатает котика
    description: Печатает котика в терминал.
    base: core24
    confinement: strict
    grade: stable
    apps:
      hello-cat:
        command: bin/hello-cat
        plugs: [home, network]
        environment:
          COWPATH: $SNAP/usr/share/cowsay/cows

| Поле | Смысл |
|---|---|
| `base` | минимальная система под снапом: `core22` (Ubuntu 22.04), `core24` |
| `confinement` | `strict` — коробка, `classic` — без неё (редакторы, IDE), `devmode` — для отладки |
| `plugs` | что можно снаружи: `home`, `network`, `x11`, `audio-playback`… |
| `$SNAP` | где снап смонтирован внутри коробки |

## Сборка

Обычно — `snapcraft` по рецепту `snap/snapcraft.yaml`: он сам собирает части (`parts`) в
чистой ВМ или контейнере (LXD, multipass), раскладывает их в каталог `prime/` и упаковывает:

    $ snapcraft          # то же, что в конце: snap pack prime/

    $ snap pack каталог                       # → имя_версия_архитектура.snap
    $ unsquashfs -l файл.snap                  # что внутри
    $ sudo snap install --dangerous файл.snap  # свой, неподписанный
    $ snap run hello-cat

## Источники

- [Snapcraft documentation](https://snapcraft.io/docs)
- [snap.yaml reference](https://snapcraft.io/docs/snap-format)
- [Interfaces](https://snapcraft.io/docs/supported-interfaces)

# snap

**snap** — пакеты Canonical: в Ubuntu так приходят Firefox, Chromium, VS Code. Снап — сжатый
образ (squashfs) каталога с программой и **всем, что ей нужно**. Ставит их `snapd`, обновляет
сам, а работает каждый снап в своей коробке: системные файлы ему не видны.

Внутри снапа:

```
hello-cat-dir/
├── meta/
│   └── snap.yaml   ← паспорт
└── bin/
    └── hello-cat
```

`meta/snap.yaml`:

```yaml
name: hello-cat
version: '0.3'
summary: Печатает котика
description: Печатает котика в терминал.
base: core24              # минимальная система, поверх которой работает снап
confinement: strict       # коробка закрыта
grade: stable
architectures: [all]      # скрипт — для любого процессора
apps:
  hello-cat:
    command: bin/hello-cat   # путь — от корня снапа
```

Обычно снапы собирает `snapcraft` из рецепта `snapcraft.yaml`: он раскладывает файлы в каталог
и в конце упаковывает его командой `snap pack`. Ей и соберём:

```sh
snap pack hello-cat-dir
```

Исходники pelmeni — в `~/pelmeni`.

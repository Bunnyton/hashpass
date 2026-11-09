# Всё своё — с собой

В песочнице flatpak программы системы не видны: `/usr` там — от runtime, а `files/` приложения
смонтирован как `/app`. `PATH` уже содержит `/app/bin`.

Готовое из пакетов Debian кладут внутрь без установки:

```sh
apt-get download cowsay                 # .deb в текущий каталог, root не нужен
dpkg -x cowsay_*.deb cowsay-root        # распаковать файлы пакета в каталог
```

Внутри `.deb` пути системные — `usr/bin`, `usr/share`, — а у приложения тот же порядок лежит прямо
в `files/`: `files/bin`, `files/share`. `dpkg -x` только распаковывает: что делают скрипты пакета
при установке (например, ссылки на команды), не появится.

Переменные окружения приложению задают в `metadata`:

```ini
[Environment]
COWPATH=/app/share/cowsay/cows
```

Ключ `--env=` у `build-finish` пишет то же самое, но `build-finish` срабатывает один раз:
второй раз он ответит `already finalized`. Дописать в готовый `metadata` можно и руками.
`figlet` ищет шрифты в каталоге из `FIGLET_FONTDIR`.

Поменял приложение — снова `build-export` и `build-bundle`.

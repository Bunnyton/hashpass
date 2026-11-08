# Всё своё — с собой

Снап не видит программ системы: внутри коробки `/usr/bin` — от `base`, а свой каталог снапа
доступен как `$SNAP`. `snapd` сам добавляет в `PATH` `$SNAP/usr/bin` и `$SNAP/bin`.

Готовое из пакетов Debian кладут внутрь без установки:

```sh
apt-get download cowsay                 # .deb в текущий каталог, root не нужен
dpkg -x cowsay_*.deb hello-cat-dir      # распаковать файлы пакета в каталог снапа
```

`dpkg -x` только распаковывает: что делают скрипты пакета при установке (например, ссылки на
команды), не появится.

Переменные окружения приложению задают в `snap.yaml`:

```yaml
apps:
  hello-cat:
    command: bin/hello-cat
    environment:
      COWPATH: $SNAP/usr/share/cowsay/cows
```

`figlet` ищет шрифты в каталоге из `FIGLET_FONTDIR`.

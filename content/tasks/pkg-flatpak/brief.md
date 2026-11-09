# flatpak

**flatpak** — «приложение на любой Linux» от мира GNOME, KDE и Fedora: из Flathub так ставят
Telegram, OBS, GIMP. Каждое приложение работает в песочнице поверх **runtime** — общей
минимальной системы (`org.freedesktop.Platform`, `org.gnome.Platform`…), а всё своё несёт в
каталоге, который внутри песочницы виден как `/app`.

Приложение называют перевёрнутым доменом: `org.example.Hello`, `org.telegram.desktop`.

Внутри приложения:

```
hello-app/
├── metadata        ← паспорт
└── files/          ← станет /app
    └── bin/
        └── hello
```

`metadata` — ini-файл:

```ini
[Application]
name=org.example.Hello
runtime=org.freedesktop.Platform/x86_64/24.08
sdk=org.freedesktop.Sdk/x86_64/24.08
```

Обычно всё делает `flatpak-builder` по манифесту: скачивает runtime и SDK, собирает программу в
песочнице, раскладывает в `files/` и упаковывает. Песочнице нужен `bwrap`, а runtime — гигабайты
из сети, поэтому здесь пройдём те же последние шаги руками:

```sh
flatpak build-finish hello-app --command=hello          # какую команду запускать — в metadata
flatpak build-export repo hello-app                     # коммит в репозиторий ostree ./repo
flatpak build-bundle repo hello.flatpak org.example.Hello   # приложение из репозитория — в один файл
```

`flatpak run` здесь не запустится — по той же причине, что и сборщик.

Исходники pelmeni — в `~/pelmeni`.

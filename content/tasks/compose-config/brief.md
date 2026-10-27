# Compose: свой образ и настройки

Образ для сервиса compose берёт из реестра — по имени в `image:`. Но compose умеет и
**собрать** образ сам, если ему сказать, где рецепт:

    services:
      api:
        build: ./api        # каталог, где лежит Dockerfile

`docker compose up` тогда соберёт образ (при первом запуске) и запустит контейнер — как
`docker build` и `docker run` в одной команде.

Переменные окружения контейнера в `compose.yaml` задаёт раздел `environment` — то же, что
`-e` у `docker run`.

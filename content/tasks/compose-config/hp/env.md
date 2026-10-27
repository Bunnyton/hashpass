# Переменные в compose.yaml

compose подставляет в `compose.yaml` переменные, как оболочка: `${ИМЯ}` заменяется значением.
Значения он берёт из окружения и из файла **`.env`** рядом с `compose.yaml` — по строке
`ИМЯ=значение`:

    # .env
    NGINX_VERSION=1.27
    WEB_PORT=8080

    # compose.yaml
    services:
      web:
        image: nginx:${NGINX_VERSION}
        ports:
          - "${WEB_PORT}:80"

Значение с пробелами в `.env` берут в кавычки. Что получилось после подстановки, покажет
`docker compose config`.

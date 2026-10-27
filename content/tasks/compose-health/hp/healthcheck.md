# Запущен — ещё не значит готов

Порядок запуска в compose задаёт `depends_on`:

    services:
      web:
        depends_on:
          - db

Но так compose ждёт только, пока контейнер db **запустится**. Готов ли он отвечать, compose
не знает — база может ещё минуту читать свои файлы.

Чтобы знал, у сервиса описывают **healthcheck** — проверку здоровья: команду, которую docker
сам запускает внутри контейнера раз в несколько секунд. Код 0 — здоров.

    db:
      image: postgres:16
      healthcheck:
        test: ["CMD", "pg_isready", "-U", "postgres"]
        interval: 5s        # как часто проверять
        retries: 5          # сколько неудач подряд — и статус unhealthy

Проверка зависит от сервиса: `pg_isready` для PostgreSQL, `redis-cli ping` для redis,
`wget -qO- http://localhost/` для того, что отвечает по HTTP. Программа проверки должна быть
в образе самого сервиса.

А ждать здоровья, а не запуска, `depends_on` умеет в длинной записи:

    depends_on:
      db:
        condition: service_healthy

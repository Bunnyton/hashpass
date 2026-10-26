# Каталоги в compose.yaml

Всё, что ты писал ключами `docker run`, в compose.yaml — поля сервиса. Подключённый каталог
(`-v`) — поле `volumes`, список в той же записи «откуда:куда»:

    services:
      blog:
        image: nginx
        volumes:
          - ./site:/usr/share/nginx/html

В compose.yaml путь можно писать от каталога, где лежит сам файл, — `./site`.

Поменял compose.yaml — снова `docker compose up -d`: compose сам пересоздаст только те
контейнеры, описание которых изменилось.

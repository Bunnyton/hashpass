#!/bin/sh
# Сервис заказов: при старте один раз проверяет базу db; нет ответа — завершается с ошибкой.
# Падает и сам, если в контейнере появился /tmp/crash (так проверяют, поднимет ли его docker).
echo "app: подключаюсь к базе db"
if ! wget -qO- -T 2 http://db/ >/dev/null 2>&1; then
    echo "app: база недоступна — выхожу"
    exit 1
fi
echo "app: база на связи, принимаю заказы на порту 80"
httpd -p 80 -h /www
while sleep 1; do
    if [ -e /tmp/crash ]; then rm -f /tmp/crash; echo "app: упал"; exit 3; fi
done

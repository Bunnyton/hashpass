#!/bin/sh
# Сервис расчётов «Пельменя»: подключается к базе (адрес — в DB_URL) и раз в минуту
# пересчитывает отчёт /data/report.csv. Без DB_URL работать не может — и честно об этом пишет.
echo "billing: старт, версия 2.4"
if [ -z "$DB_URL" ]; then
    echo "billing: ОШИБКА — не задана переменная окружения DB_URL (адрес базы заказов)" >&2
    echo "billing: завершаюсь" >&2
    exit 1
fi
echo "billing: база — $DB_URL"
mkdir -p /data
while true; do
    cp /app/report.csv /data/report.csv
    echo "billing: отчёт обновлён, заказов: $(($(wc -l < /data/report.csv) - 1))"
    sleep 60
done

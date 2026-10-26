#!/bin/sh
# Витрина: каждые 2 секунды берёт остатки со склада (http://stock/stock.txt) и рисует страницу.
# Склад ищется по имени stock — так его зовут в общей сети контейнеров.
mkdir -p /www
httpd -p 80 -h /www
while true; do
    if data=$(wget -qO- -T 2 http://stock/stock.txt 2>&1); then
        rows=$(printf '%s\n' "$data" | tail -n +2 | awk -F';' '{ printf "<tr><td>%s</td><td>%s шт.</td></tr>", $1, $2 }')
        body="<h1>Витрина «Пельменя»</h1><table>$rows</table>"
    else
        body="<h1>Витрина «Пельменя»</h1><p>Склад недоступен: $data</p>"
    fi
    printf '<!doctype html><meta charset="utf-8"><title>Витрина</title>%s\n' "$body" > /www/index.html.new
    mv /www/index.html.new /www/index.html
    sleep 2
done

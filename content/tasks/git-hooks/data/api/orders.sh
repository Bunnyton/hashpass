#!/bin/sh
# Сервис заказов «Пельменя»: принимает заказ и пишет его в журнал.
. "$(dirname "$0")/settings.env"
dish=$1 count=${2:-1}
echo "$(date +%F) $dish x$count" >> "$ORDERS_LOG"
echo "Принято: $dish × $count"

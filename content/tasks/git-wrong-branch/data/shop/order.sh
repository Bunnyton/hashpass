#!/bin/sh
# Заказ в «Пельмене»: сумма по позициям.
# Запуск: ./order.sh <блюдо> <количество> [<блюдо> <количество> …]
total=0
while [ $# -ge 2 ]; do
    price=$(awk -v d="$1" '$1 == d { print $2 }' prices.txt)
    [ -n "$price" ] || { echo "Нет в меню: $1" >&2; exit 1; }
    total=$((total + price * $2))
    shift 2
done
echo "К оплате: $total ₽"

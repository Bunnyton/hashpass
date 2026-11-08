#!/bin/sh
# Сумма заказа: ./order.sh <блюдо> <количество>
price=$(awk -v d="$1" '$1 == d { print $2 }' menu.txt)
[ -n "$price" ] || { echo "Нет в меню: $1" >&2; exit 1; }
echo "К оплате: $((price * ${2:-1})) ₽"

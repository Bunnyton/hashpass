#!/bin/sh
# Сумма заказа: ./order.sh <блюдо> <количество>; CLIENT=<телефон> — скидка постоянным 5 %
price=$(awk -v d="$1" '$1 == d { print $2 }' menu.txt)
[ -n "$price" ] || { echo "Нет в меню: $1" >&2; exit 1; }
total=$((price * ${2:-1}))
if [ -n "$CLIENT" ] && grep -qx "$CLIENT" regulars.txt; then
    total=$((total - total * 5 / 100))
fi
echo "К оплате: $total ₽"

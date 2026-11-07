#!/bin/sh
# Сумма заказа: ./price.sh <блюдо> <количество> [<блюдо> <количество> …]
cd "$(dirname "$0")"
total=0
while [ $# -ge 2 ]; do
    p=$(awk -v d="$1" '$1 == d { print $2 }' prices.txt)
    [ -n "$p" ] || { echo "Нет в меню: $1" >&2; exit 1; }
    total=$((total + p * $2))
    shift 2
done
echo "$total"

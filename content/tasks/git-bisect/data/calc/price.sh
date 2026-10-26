#!/bin/sh
# Сумма заказа: ./price.sh <цена за штуку> <штук> <скидка %> — в рублях, без копеек.
price=$1
count=$2
discount=$3
total=$(( price * count ))
total=$(( total - total * discount / 100 ))
echo "$total"

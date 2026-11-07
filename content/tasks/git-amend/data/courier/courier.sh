#!/bin/sh
# Курьерский бот «Пельменя»: сколько стоит доставка по адресу.
# Запуск: ./courier.sh <зона>
zone=${1:-}
if [ -z "$zone" ]; then
    echo "Укажи зону доставки: ./courier.sh <зона>" >&2
    exit 1
fi
price=$(awk -v z="$zone" '$1 == z { print $2 }' tariffs.txt)
if [ -z "$price" ]; then
    echo "В зону «$zone» пока не возим." >&2
    exit 1
fi
echo "Доставка в зону «$zone»: $price ₽"

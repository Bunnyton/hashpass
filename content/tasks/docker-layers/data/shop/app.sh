#!/bin/sh
# Прайс-лист лавки: товар;цена из prices.txt
. /opt/deps/money.sh
echo "Лавка «У дома» — цены сегодня"
while IFS=';' read -r item price; do
    [ -n "$item" ] || continue
    echo "  $item — $(money "$price")"
done < /app/prices.txt

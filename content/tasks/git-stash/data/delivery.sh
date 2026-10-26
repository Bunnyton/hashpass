#!/bin/sh
# Стоимость доставки: ./delivery.sh <сумма заказа>. От 3000 ₽ — бесплатно.
if [ "$1" -ge 3000 ]; then echo 0; else echo 300; fi

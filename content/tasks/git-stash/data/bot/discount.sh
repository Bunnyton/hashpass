#!/bin/sh
# Цена со скидкой: ./discount.sh <цена> <скидка в процентах>
price=$1
percent=$2
echo $(( price - price * percent ))

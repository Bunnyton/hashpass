#!/bin/sh
# Бот магазина «Пельмень»: отвечает на команды покупателей.
# ./bot.sh <команда> [аргументы]
here=$(dirname "$0")
case "$1" in
    hello)   sed -n 1p "$here/messages.txt" ;;
    price)   echo "Цена со скидкой: $("$here/discount.sh" "$2" "$3") ₽" ;;
    hours)   sed -n 2p "$here/messages.txt" ;;
    *)       echo "Не понимаю. Команды: hello, price, hours" ;;
esac

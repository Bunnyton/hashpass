#!/bin/sh
# Проверка калькулятора: ./test.sh — молчит и выходит с 0, если всё сходится.
here=$(dirname "$0")
fail=0
check() {  # check <цена> <штук> <скидка> <ожидаемо>
    got=$("$here/price.sh" "$1" "$2" "$3")
    if [ "$got" != "$4" ]; then
        echo "ОШИБКА: $1 ₽ × $2 шт., скидка $3 % — ждали $4, получили $got"
        fail=1
    fi
}
check 349 1 0 349
check 349 3 0 1047
check 1000 1 10 900
check 249 4 15 847
check 199 10 5 1891
exit $fail

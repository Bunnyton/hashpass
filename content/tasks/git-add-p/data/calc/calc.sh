#!/bin/sh
# Калькулятор: ./calc.sh 12 + 5
usage() {
    echo "Использование: ./calc.sh <число> <операция> <число>"
    echo "Операции: + - x /"
}
a=$1 op=$2 b=$3
[ -n "$b" ] || { usage >&2; exit 2; }

case "$op" in
    +) echo $((a + b)) ;;
    -) echo $((a - b)) ;;
    x) echo $((a * b)) ;;
    /) echo $((a / b)) ;;
    *) echo "Не знаю операцию: $op" >&2; usage >&2; exit 2 ;;
esac

#!/bin/sh
# Калькулятор: ./calc.sh 12 + 5
pow() {  # TODO: отрицательные степени, а ещё ^ в case ниже
    r=1 i=0; while [ "$i" -lt "$2" ]; do r=$((r * $1)); i=$((i + 1)); done; echo "$r"
}
usage() {
    echo "Использование: ./calc.sh <число> <операция> <число>"
    echo "Операции: + - x / ^"
}
a=$1 op=$2 b=$3
[ -n "$b" ] || { usage >&2; exit 2; }

case "$op" in
    +) echo $((a + b)) ;;
    -) echo $((a - b)) ;;
    x) echo $((a * b)) ;;
    /) [ "$b" -ne 0 ] || { echo "На ноль делить нельзя" >&2; exit 1; }; echo $((a / b)) ;;
    *) echo "Не знаю операцию: $op" >&2; usage >&2; exit 2 ;;
esac

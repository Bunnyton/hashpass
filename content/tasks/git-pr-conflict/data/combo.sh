#!/bin/sh
# Комбо-обед: пельмени + морс, скидка 10 %: ./combo.sh <пельмени>
sum=0
for item in "$1" морс; do
    p=$(./order.sh "$item" 1 | sed 's/^К оплате: \([0-9]*\) ₽$/\1/')
    sum=$((sum + p))
done
echo "Комбо: $((sum - sum / 10)) ₽"

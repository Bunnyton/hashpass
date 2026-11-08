#!/bin/sh
# Проверки кассы — их запускает и Лепка на каждом pull request.
fail=0
check() { out=$(./order.sh "$1" "$2" 2>&1); [ "$out" = "$3" ] && echo "ok   $1 x$2" || { echo "FAIL $1 x$2: «$out», ждали «$3»"; fail=1; }; }
check пельмени-говядина 2 "К оплате: 700 ₽"
check морс 3 "К оплате: 360 ₽"
for d in $(awk '{ print $1 }' menu.txt); do
    awk -v d="$d" '$1 == d && $2 !~ /^[0-9]+$/ { exit 1 }' menu.txt || { echo "FAIL $d: цена не число"; fail=1; }
done
exit $fail

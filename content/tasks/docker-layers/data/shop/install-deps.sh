#!/bin/sh
# Ставит библиотеки из deps.txt в /opt/deps. Каждая собирается пару секунд — как настоящие.
set -e
mkdir -p /opt/deps
while read -r dep; do
    [ -n "$dep" ] || continue
    echo "ставлю $dep..."
    sleep 2
    echo "# библиотека $dep" > "/opt/deps/$dep.sh"
done < /app/deps.txt
cat >> /opt/deps/money.sh <<'LIB'
money() { echo "$1 ₽"; }
LIB
echo "готово: $(ls /opt/deps | wc -l) библиотек"

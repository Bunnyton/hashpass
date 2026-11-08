#!/bin/sh
# Собрать «сервер» кассы и клон студента; на сервер ставится хук post-receive Лепки.
# Даты и авторы фиксированы — хеши стабильны. Запуск: mkrepo.sh <data> <сервер.git> <клон>
set -eu
src=$1 srv=$2 dst=$3
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
c() {
    n=$((n + 1))
    d="2026-10-$((10 + n))T1$((n % 10)):05:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
cp "$src/shop/README.md" . && anna "README"
grep -v -e '^морс' -e '^сметана' "$src/shop/menu.txt" > menu.txt
cp "$src/shop/order.sh" "$src/shop/test.sh" . && chmod 755 order.sh test.sh
sed -i '/^check морс/d' test.sh
printf '# Что нового\n\n- касса считает сумму заказа\n' > CHANGELOG.md
anna "Касса: сумма заказа и проверки"
grep '^морс' "$src/shop/menu.txt" >> menu.txt && cp "$src/shop/test.sh" test.sh
printf '# Что нового\n\n- морс\n- касса считает сумму заказа\n' > CHANGELOG.md; anna "Морс"
cp "$src/shop/menu.txt" "$src/shop/CHANGELOG.md" . && anna "Сметана к пельменям"
git clone -q --bare "$work" "$srv"
cd / && rm -rf "$work"
install -m 755 /usr/local/lib/lepka/post-receive /usr/local/lib/lepka/pre-receive "$srv/hooks/"
git clone -q "$srv" "$dst"

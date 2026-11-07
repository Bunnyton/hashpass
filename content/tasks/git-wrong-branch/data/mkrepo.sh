#!/bin/sh
# Собрать «сервер» кассы (голый репозиторий) и клон студента, в котором три коммита про купоны
# сделаны прямо в main и ещё не отправлены. Даты и авторы зафиксированы: вершина купонов —
# одна и та же на любой машине (её сверяет hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <сервер.git> <клон>
set -eu
src=$1 srv=$2 dst=$3
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-$((10 + n))T1$((n % 10)):05:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
me()   { c "Студент" "student@hashpass.local" "$1"; }
put() { cp "$src/shop/$1" "$1" && chmod "$2" "$1"; }   # режим файла входит в хеш
put README.md 644; anna "README"
put prices.txt 644; anna "Цены"
put order.sh 755; anna "Касса: сумма заказа"
sed -i 's/^морс               120$/морс               130/' prices.txt; anna "Морс подорожал"
git clone -q --bare "$work" "$srv"
cd / && rm -rf "$work"
git clone -q "$srv" "$dst"
cd "$dst"
# купоны — прямо в main, на сервер ещё не ушли
cat > coupons.txt <<'TXT'
# код        скидка, %
WELCOME10    10
FRIDAY15     15
STUDENT20    20
TXT
chmod 644 coupons.txt; me "Купоны: таблица кодов"
cat > coupon.sh <<'SH'
#!/bin/sh
# Скидка по купону: ./coupon.sh <код> — печатает процент или ругается.
pct=$(awk -v c="$1" '$1 == c { print $2 }' coupons.txt)
[ -n "$pct" ] || { echo "Купон $1 не найден" >&2; exit 1; }
echo "$pct"
SH
chmod 755 coupon.sh; me "Купоны: проверка кода"
cat >> README.md <<'TXT'

Купон: COUPON=FRIDAY15 ./order.sh пельмени-курица 2
TXT
sed -i 's/^echo "К оплате: $total ₽"$/if [ -n "${COUPON:-}" ]; then\n    pct=$(.\/coupon.sh "$COUPON") || exit 1\n    total=$((total - total * pct \/ 100))\nfi\necho "К оплате: $total ₽"/' order.sh
me "Купоны: скидка в чеке"

#!/bin/sh
# Собрать кассу с PR Олега «Скидка постоянным клиентам» (#1): два коммита — расчёт скидки
# (с ошибкой: второй вычет всем) и тесты, подогнанные под ошибку. Ревьюер — студент.
# Исправление (для бота) кладётся в /usr/local/lib/lepka/fix. Хеши стабильны.
# Запуск (root): mkrepo.sh <data> <сервер.git> <клон>
set -eu
src=$1 srv=$2 dst=$3
L="python3 /usr/local/lib/lepka/lepka.py"
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
oleg() { c "Олег Кузнецов" "oleg@pelmen.local" "$1"; }
cp "$src/shop/README.md" "$src/shop/menu.txt" "$src/shop/CHANGELOG.md" .
cp "$src/shop/order.sh" "$src/shop/test.sh" . && chmod 755 order.sh test.sh
anna "Касса: меню, сумма заказа, проверки"
git clone -q --bare "$work" "$srv"
install -m 755 /usr/local/lib/lepka/post-receive /usr/local/lib/lepka/pre-receive "$srv/hooks/"
git switch -q -c regulars
cp "$src/order-bug.sh" order.sh && cp "$src/regulars.txt" .
sed -i 's/^# Что нового$/# Что нового\n\n- скидка 5 % постоянным клиентам/' CHANGELOG.md
oleg "Скидка постоянным: regulars.txt и расчёт"
sed -i 's/"К оплате: 700 ₽"/"К оплате: 665 ₽"/; s/"К оплате: 360 ₽"/"К оплате: 342 ₽"/' test.sh
oleg "Тесты под скидку"
LEPKA_INTERNAL=1 git push -q "$srv" regulars
# исправление — для бота Олега
install -d /usr/local/lib/lepka/fix
cp "$src/order-fix.sh" /usr/local/lib/lepka/fix/order.sh
sed 's/"К оплате: 665 ₽"/"К оплате: 700 ₽"/; s/"К оплате: 342 ₽"/"К оплате: 360 ₽"/' test.sh > /usr/local/lib/lepka/fix/test.sh
printf 'out=$(CLIENT=+79990001122 ./order.sh пельмени-говядина 2); [ "$out" = "К оплате: 665 ₽" ] && echo "ok   постоянный клиент" || { echo "FAIL постоянный клиент: «$out», ждали «К оплате: 665 ₽»"; fail=1; }\n' > t.add
sed -i '/^exit \$fail$/e cat t.add' /usr/local/lib/lepka/fix/test.sh
cd / && rm -rf "$work"
git clone -q "$srv" "$dst"
LEPKA_ME=oleg $L open shop regulars oleg "Скидка 5 % постоянным клиентам" "Постоянные — по номеру телефона из regulars.txt: CLIENT=+79990001122 ./order.sh пельмени-говядина 2. Тесты обновил." >/dev/null

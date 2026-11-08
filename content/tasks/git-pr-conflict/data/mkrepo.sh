#!/bin/sh
# Собрать кассу для PR с конфликтом: ветка студента combo (комбо-обед) с открытым и уже
# одобренным PR #1; потом PR #2 Олега («Итого» вместо «К оплате» в чеке) влит в main.
# Теперь у PR #1 конфликт в CHANGELOG.md (обе ветки дописали строку наверх), а после его
# разбора падает ./test.sh: combo.sh разбирает старый формат чека. Хеши стабильны.
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
me()   { c "Студент" "student@hashpass.local" "$1"; }
cp "$src/shop/README.md" "$src/shop/menu.txt" "$src/shop/CHANGELOG.md" .
cp "$src/shop/order.sh" "$src/shop/test.sh" . && chmod 755 order.sh test.sh
anna "Касса: меню, сумма заказа, проверки"
git clone -q --bare "$work" "$srv"
install -m 755 /usr/local/lib/lepka/post-receive /usr/local/lib/lepka/pre-receive "$srv/hooks/"
# ветка студента: комбо-обед
git switch -q -c combo
cp "$src/combo.sh" . && chmod 755 combo.sh
printf 'check_combo() { [ "$(./combo.sh пельмени-говядина)" = "Комбо: 423 ₽" ] && echo "ok   комбо" || { echo "FAIL комбо: «$(./combo.sh пельмени-говядина 2>&1)», ждали «Комбо: 423 ₽»"; fail=1; }; }\ncheck_combo\n' > t.add
sed -i '/^exit \$fail$/e cat t.add' test.sh && rm t.add
me "Комбо-обед: пельмени + морс со скидкой"
sed -i 's/^# Что нового$/# Что нового\n\n- комбо-обед: пельмени и морс со скидкой 10 %/' CHANGELOG.md
sed -i '4{/^$/d}' CHANGELOG.md
me "CHANGELOG: комбо-обед"
LEPKA_INTERNAL=1 git push -q "$srv" combo
# ветка Олега: «Итого» в чеке
git switch -q main
git switch -q -c receipt
sed -i 's/К оплате:/Итого:/' order.sh test.sh
oleg "Чек: «Итого» вместо «К оплате»"
sed -i 's/^# Что нового$/# Что нового\n\n- в чеке теперь «Итого»/' CHANGELOG.md
sed -i '4{/^$/d}' CHANGELOG.md
oleg "CHANGELOG: «Итого»"
LEPKA_INTERNAL=1 git push -q "$srv" receipt
cd / && rm -rf "$work"
# клон студента — до того, как PR Олега влили: origin/main старый
git clone -q -b combo "$srv" "$dst"
git -C "$dst" branch -q main origin/main
LEPKA_ME=student $L open shop combo student "Комбо-обед" "Пельмени + морс со скидкой 10 %. ./combo.sh пельмени-говядина" >/dev/null
LEPKA_ME=oleg $L open shop receipt oleg "Чек: «Итого» вместо «К оплате»" "Так короче и как у всех." >/dev/null
LEPKA_ME=anna $L merge shop 2 merge delete

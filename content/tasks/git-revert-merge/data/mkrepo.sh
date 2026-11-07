#!/bin/sh
# Собрать кассу: в main влили ветку promo (акция −10 %), и тест упал — акция срезает и мелкие
# заказы. После слияния в main ещё два хороших коммита. Даты и авторы зафиксированы: хеши
# одинаковы на любой машине (их сверяет hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
when() { n=$((n + 1)); echo "2026-10-$((10 + n))T15:00:00+03:00"; }
c() {  # c "имя" "почта" "сообщение"
    d=$(when)
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.local" "$1"; }
put() { cp "$src/kassa/$1" "$1" && chmod "$2" "$1"; }
put README.md 644; put prices.txt 644; put price.sh 755; anna "Касса: сумма заказа"
put test.sh 755; anna "Тест кассы"
git switch -q -c promo
cat > promo.sh <<'SH'
#!/bin/sh
# Акция «Пельмень-пятница»: скидка 10 % на заказ. ./promo.sh <сумма> — печатает сумму со скидкой.
echo $(( $1 - $1 / 10 ))
SH
chmod 755 promo.sh; oleg "Акция: скрипт скидки"
sed -i 's|^echo "\$total"$|[ -x ./promo.sh ] \&\& total=$(./promo.sh "$total")\necho "$total"|' price.sh
oleg "Акция: касса считает скидку"
printf '\nАкция «Пельмень-пятница»: скидка 10 %% — считает promo.sh.\n' >> README.md
oleg "Акция: README"
git switch -q main
sed -i 's/^морс               130$/морс               140/' prices.txt; anna "Морс подорожал"
d=$(when)
GIT_AUTHOR_NAME="Анна Смирнова" GIT_AUTHOR_EMAIL="anna@pelmen.local" GIT_AUTHOR_DATE="$d" \
GIT_COMMITTER_NAME="Анна Смирнова" GIT_COMMITTER_EMAIL="anna@pelmen.local" GIT_COMMITTER_DATE="$d" \
    git merge -q --no-ff --no-edit -m "Merge branch 'promo'" promo
sed -i 's/^пельмени-курица    350$/пельмени-курица    360/' prices.txt
sed -i 's/check 700  пельмени-курица 2/check 720  пельмени-курица 2/; s/check 1040 пельмени-говядина 2 морс 2/check 1060 пельмени-говядина 2 морс 2/' test.sh
anna "Курица подорожала"
printf 'сметана             40\n' >> prices.txt; anna "Сметана в меню"

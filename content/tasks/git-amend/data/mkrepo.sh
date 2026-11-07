#!/bin/sh
# Собрать курьерского бота с историей. Последний коммит «Тарифы доставки по зонам» сделан с
# ноутбука Васи: в .git/config лежат его имя и почта, а сам tariffs.txt в коммит не попал.
# Даты и авторы зафиксированы — хеши одинаковы на любой машине: коммит перед Васиным — его
# сверяет hp/state.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-1${n}T1${n}:20:00+03:00"
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
me() { c "Студент" "student@hashpass.local" "$1"; }
put() { cp "$src/courier/$1" "$1" && chmod "$2" "$1"; }   # режим файла входит в хеш
put README.md 644; git add README.md; me "README"
put zones.txt 644; git add zones.txt; me "Зоны доставки"
# первая версия: одна цена на всех
cat > courier.sh <<'SH'
#!/bin/sh
# Курьерский бот «Пельменя»: сколько стоит доставка.
echo "Доставка: 190 ₽"
SH
chmod 755 courier.sh; git add courier.sh; me "Бот: доставка 190 ₽"
# вечер у Васи: его настройки в репозитории, тарифы по зонам — а tariffs.txt не добавлен
git config user.name "Вася Пупкин"
git config user.email "vasya@pelmen.local"
put courier.sh 755; put tariffs.txt 644
git add courier.sh
c "Вася Пупкин" "vasya@pelmen.local" "Тарифы доставки по зонам"

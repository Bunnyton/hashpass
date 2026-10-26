#!/bin/sh
# Собрать репозиторий API: main и ветка search, которая ответвилась давно. Пока в search
# шла работа, в main появилось четыре коммита, один из них тоже дописал строку в CHANGELOG.md
# туда же, куда и search, — при переносе ветки будет конфликт. Даты и авторы зафиксированы.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/api/. "$dst"/
cd "$dst"
chmod 644 ./*
git init -q -b main
n=0
c() {  # c "Автор" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-$(printf %02d "$n")T1$((n % 9)):30:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
me()   { c "Студент" "student@hashpass.local" "$1"; }
anna() { c "Анна Смирнова" "anna@pelmen.shop" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.shop" "$1"; }
log() { sed -i "s/^## Не выпущено$/## Не выпущено\n\n- $1/" CHANGELOG.md; sed -i '/^## Не выпущено$/{n;/^$/{n;/^$/d}}' CHANGELOG.md; }
anna "API 1.0"
# ветка search: три коммита
git switch -q -c search
sed -i "s|^GET  /products/<id>     один товар$|&\nGET  /search?q=<текст>  поиск по названию|" routes.txt; me "Маршрут поиска"
log "Поиск товаров по названию: GET \/search."; me "CHANGELOG: поиск"
sed -i "s|^GET  /search?q=<текст>  поиск по названию$|GET  /search?q=<текст>&limit=<n>  поиск по названию, не больше n результатов|" routes.txt; me "Поиск: ограничение числа результатов"
# тем временем в main
git switch -q main
sed -i "s|^GET  /orders/<id>       статус заказа$|&\nDELETE /orders/<id>    отменить заказ|" routes.txt; oleg "Отмена заказа"
log "Отмена заказа: DELETE \/orders\/<id>."; oleg "CHANGELOG: отмена заказа"
printf '\nОшибки — JSON вида {"error": "..."}.\n' >> CONTRIBUTING.md; anna "Договорились о формате ошибок"
sed -i 's/список товаров/список товаров (по 20 на страницу)/' routes.txt; anna "Товары по страницам"
git switch -q search

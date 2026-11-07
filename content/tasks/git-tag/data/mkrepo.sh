#!/bin/sh
# Собрать «сервер» приложения доставки и клон студента: 12 коммитов, релизы 1.9 и 2.0.
# Тег v1.9 коллега по ошибке повесил на коммит после релиза («Начало 2.0»), он уже на
# сервере; v2.0 нет вовсе. Даты фиксированы — хеши стабильны (hp/state).
# Запуск: mkrepo.sh <сервер.git> <клон>
set -eu
srv=$1 dst=$2
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-$((10 + n))T1$((n % 10)):25:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.local" "$1"; }
printf '# Приложение доставки «Пельменя»\n' > README.md; anna "README"
echo 1.8 > VERSION; printf 'меню\nкорзина\n' > features.txt; anna "Релиз 1.8"
echo "оплата картой" >> features.txt; oleg "Оплата картой"
echo "трекинг курьера" >> features.txt; oleg "Трекинг курьера"
echo 1.9 > VERSION; anna "Релиз 1.9: версия в VERSION"
printf 'format=2\n' > data.conf; oleg "Начало 2.0: новый формат данных"
echo "отзывы" >> features.txt; oleg "Отзывы"
echo "промокоды" >> features.txt; anna "Промокоды"
echo 2.0 > VERSION; anna "Релиз 2.0: версия в VERSION"
echo "тёмная тема" >> features.txt; oleg "Тёмная тема (черновик)"
echo "чат с поддержкой" >> features.txt; oleg "Чат с поддержкой (черновик)"
printf '\nВерсии — в VERSION, релизы помечены тегами.\n' >> README.md; anna "README: версии"
GIT_COMMITTER_NAME="Анна Смирнова" GIT_COMMITTER_EMAIL="anna@pelmen.local" \
GIT_COMMITTER_DATE="2026-10-16T18:00:00+03:00" \
    git tag -a v1.8 -m "Версия 1.8" HEAD~10
GIT_COMMITTER_NAME="Олег Кузнецов" GIT_COMMITTER_EMAIL="oleg@pelmen.local" \
GIT_COMMITTER_DATE="2026-10-17T18:00:00+03:00" \
    git tag -a v1.9 -m "Версия 1.9" HEAD~6
git clone -q --bare "$work" "$srv"
cd / && rm -rf "$work"
git clone -q "$srv" "$dst"

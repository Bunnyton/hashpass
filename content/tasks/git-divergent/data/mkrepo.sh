#!/bin/sh
# Собрать «сервер» кофейни и клон студента: у студента свой неотправленный коммит (сырники
# в menu.txt), а Олег после клона отправил два своих (цены, README). Ветки разошлись.
# Даты и авторы зафиксированы — хеши одни на любой машине (их сверяет hp/state).
# Запуск: mkrepo.sh <сервер.git> <клон>
set -eu
srv=$1 dst=$2
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-11-$((10 + n))T1$((n % 10)):15:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
oleg() { c "Олег Кузнецов" "oleg@coffee.local" "$1"; }
me()   { c "Студент" "student@hashpass.local" "$1"; }
printf '# Кофейня «Зерно»\n\nМеню и цены. Правило: в main — прямая история.\n' > README.md
oleg "README"
printf 'эспрессо\nкапучино\nлатте\nраф\n' > menu.txt
oleg "Меню"
printf 'эспрессо   150\nкапучино   220\nлатте      240\nраф        260\n' > prices.txt
oleg "Цены"
git clone -q --bare "$work" "$srv"
git clone -q "$srv" "$dst"
# Олег отправляет два коммита — уже после того, как студент склонировал
sed -i 's/^капучино   220$/капучино   230/' prices.txt; oleg "Капучино подорожал"
printf '\nЦены — в prices.txt, меню — в menu.txt.\n' >> README.md; oleg "README: где что лежит"
git push -q "$srv" main
cd "$dst"
printf 'сырники\n' >> menu.txt
n=10; me "Меню: сырники"
cd / && rm -rf "$work"

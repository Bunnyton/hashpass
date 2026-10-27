#!/bin/sh
# Собрать репозиторий API заказов: три коммита (даты и автор зафиксированы). Хуков в нём нет —
# только примеры *.sample, которые кладёт git init.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-0${n}T1${n}:10:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
add() { cp "$src/api/$1" "$1"; }
add README.md; c "API-1: README"
add orders.sh; chmod 755 orders.sh; add settings.env; c "API-2: приём заказов"
sed -i 's/^DB_HOST=.*/&\nDB_PORT=5432/' settings.env; c "API-3: порт базы"

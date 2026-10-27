#!/bin/sh
# Собрать «сервер» сайта: голый репозиторий <git> с тремя коммитами (даты и автор
# зафиксированы), выложенную копию последнего коммита в <www> (её отдаёт веб-сервер) и твой
# клон в <home>. Своих хуков на сервере нет — только примеры.
# Запуск: mkrepo.sh <каталог-с-data> <git> <www> <home>
set -eu
src=$1 bare=$2 www=$3 home=$4
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-0${n}T1${n}:50:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
add() { cp "$src/site/$1" "$1" && chmod 644 "$1"; }
add index.html; add style.css; c "Главная"
add menu.html; c "Меню"
add contacts.html; c "Контакты"
git clone -q --bare "$work" "$bare"
mkdir -p "$www"
git --work-tree="$www" checkout -q -f main
git clone -q "$bare" "$home"
rm -rf "$work"

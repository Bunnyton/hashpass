#!/bin/sh
# Собрать репозиторий сайта: три коммита (даты и автор зафиксированы — хеши одинаковы на любой
# машине); .env с паролем закоммичен ещё в первом. Поверх — то, что git status показывает
# простынёй: журналы logs/, сборка dist/, кэш .cache/ — и новая страница contacts.html.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-1${n}T1${n}:20:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
cp "$src"/landing/index.html "$src"/landing/style.css "$src"/landing/app.js "$src"/landing/.env .
chmod 644 index.html style.css app.js .env
c "Сайт: главная, стили, заказ"
cp "$src"/landing/about.html . && chmod 644 about.html
c "Страница «О нас»"
sed -i 's/семь минут/семь минут. Навынос — тоже/' index.html
c "Главная: про навынос"
# то, что появилось после: сборка, журналы, кэш — и новая страница
cp -r "$src"/junk/. .
cp "$src"/contacts.html .

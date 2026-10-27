#!/bin/sh
# Собрать репозиторий сайта с тремя ветками от одного коммита (даты и автор зафиксированы —
# хеши одинаковы на любой машине):
#   redesign       — дизайнер переписал style.css целиком и сменил заголовок меню;
#   hotfix-prices  — новые цены с 1 ноября;
#   main           — твои правки цвета в style.css (шесть мест), подпись под заголовком меню
#                    и свои цены — всё это спорит с обеими ветками.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/site/. "$dst"/
cd "$dst"
chmod 644 menu.html style.css prices.txt    # режим файла входит в хеш
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-1${n}T1${n}:05:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
c "Сайт: меню, стили, цены"
git switch -q -c redesign
cp "$src"/redesign.css style.css
sed -i 's|<h1>Наше меню</h1>|<h1 class="title">Меню «Пельменя»</h1>|' menu.html
c "Редизайн: новые стили и заголовок"
git switch -q -c hotfix-prices main
sed -i 's/^пельмени-говядина 390$/пельмени-говядина 410/; s/^вареники-вишня 320$/вареники-вишня 340/; s/^морс 120$/морс 130/' prices.txt
c "Цены с 1 ноября"
git switch -q main
sed -i 's/color: #333;/color: #222;/; s/color: #7a2e1b;/color: #6b2817;/' style.css
c "Стили: текст темнее"
sed -i 's|<h1>Наше меню</h1>|&\n<p class="note">Варим при вас за семь минут</p>|' menu.html
c "Меню: подпись под заголовком"
sed -i 's/^пельмени-говядина 390$/пельмени-говядина 400/; s/^пельмени-свинина 370$/пельмени-свинина 380/; s/^морс 120$/морс 125/' prices.txt
c "Цены: говядина, свинина, морс"

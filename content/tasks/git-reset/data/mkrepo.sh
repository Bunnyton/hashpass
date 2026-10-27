#!/bin/sh
# Собрать репозиторий меню: три обычных коммита и два черновика «wip» сверху (даты и автор
# зафиксированы — хеши одинаковы на любой машине). Поверх — правка menu.txt и личный notes.txt,
# оба добавлены в индекс.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-0${n}T1${n}:40:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
add() { cp "$src/menu/$1" "$1" && chmod 644 "$1"; }   # режим файла входит в хеш
add menu.txt; add prices.txt; c "Меню и цены"
add style.css; c "Оформление меню"
add README.md; c "README"
# черновики: кричащие стили и новые цены
sed -i 's/#fffaf3/#ff00ff/; s/color: #333/color: #00ff00/' style.css
c "wip"
sed -i 's/^пельмени-говядина 390$/пельмени-говядина 420/; s/^морс 120$/морс 140/' prices.txt
c "wip2"
# незакоммиченное: новое блюдо в меню и личные заметки — оба в индексе
sed -i 's/^Морс клюквенный/Сырники со сметаной ......... 1 порция\nМорс клюквенный/' menu.txt
cp "$src"/notes.txt notes.txt && chmod 644 notes.txt
git add menu.txt notes.txt

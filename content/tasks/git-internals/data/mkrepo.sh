#!/bin/sh
# Собрать репозиторий отчётов: три коммита (даты и автор зафиксированы — хеши одинаковы на
# любой машине). tariffs.txt есть в последнем коммите, но стёрт из каталога (не закоммичено).
# Ещё три файла когда-то побывали в индексе и убраны оттуда, не попав в коммит, — в
# репозитории от них остались ничьи объекты: два черновика и отчёт за третий квартал.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-0${n}-28T1${n}:30:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Лёша" GIT_AUTHOR_EMAIL="lesha@pelmen.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Лёша" GIT_COMMITTER_EMAIL="lesha@pelmen.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
add() { cp "$src/reports/$1" "$1" && chmod 644 "$1"; }   # режим файла входит в хеш
add README.md; add tariffs.txt; c "Отчёты: README и тарифы"
add sales-q1.csv; c "Продажи за первый квартал"
add sales-q2.csv; c "Продажи за второй квартал"
# побывали в индексе и убраны, не попав в коммит: от них остались ничьи объекты
for f in draft-shopping.txt draft-todo.txt q3-report.csv; do
    cp "$src/$f" "$f"
    git add "$f"
    git rm -q --cached "$f"
    rm "$f"
done
rm tariffs.txt

#!/bin/sh
# Собрать репозиторий отчётов: в main — данные, в ветке report — шесть торопливых коммитов, за
# которые написан report.sh (итог — data/report.sh). Даты зафиксированы: вершина ветки report
# всегда 9714b23 (дерево b3adf78) — это дерево и есть правильный итог.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/report/. "$dst"/
cd "$dst"
chmod 644 ./*
git init -q -b main
n=0
c() {
    n=$((n + 1))
    d="2026-10-1${n}T1${n}:05:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
c "Продажи за третий квартал"
git switch -q -c report
printf '#!/bin/sh\nf=${1:-$(dirname "$0")/sales.csv}\necho "Выручка:"\n' > report.sh; chmod 755 report.sh; c "wip"
sed -n '1,5p' "$src"/report.sh > report.sh;   c "wip 2"
sed -i 's/Выручка по месяцам, ₽:/Выручка по месяцам, руб:/' report.sh;     c "опечатка"
sed -n '1,6p' "$src"/report.sh > report.sh;   c "ещё правка"
cp "$src"/report.sh report.sh;                c "wip"
printf 'Отчёт: ./report.sh\n' >> README.md;    c "готово вроде"

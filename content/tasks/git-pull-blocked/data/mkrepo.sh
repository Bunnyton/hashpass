#!/bin/sh
# Сервер расписания (голый репозиторий) и клон студента. После клона напарница отправила на
# сервер правку schedule.txt, а у студента в том же файле незакоммиченная правка и свой
# черновик report.txt (вне git). Даты и авторы зафиксированы: хеш правки напарницы одинаков
# на любой машине (его сверяет hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <сервер.git> <клон>
set -eu
src=$1 srv=$2 dst=$3
work=$(mktemp -d)
n=0
c() {  # c "сообщение" — от Анны
    n=$((n + 1))
    d="2026-10-2${n}T10:3${n}:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Анна Смирнова" GIT_AUTHOR_EMAIL="anna@pelmen.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Анна Смирнова" GIT_COMMITTER_EMAIL="anna@pelmen.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
cd "$work"
git init -q -b main
cp "$src/duty/README.md" "$src/duty/schedule.txt" .; chmod 644 README.md schedule.txt; c "Расписание на ноябрь"
cp "$src/duty/duty.sh" .; chmod 755 duty.sh; c "duty.sh: кто дежурит"
git clone -q --bare "$work" "$srv"
git clone -q "$srv" "$dst"
# напарница: Игорь в отпуске, вторник берёт она — и сразу на сервер
sed -i "s/^вт  Игорь$/вт  Анна/" schedule.txt; c "Вторник: Игорь в отпуске, дежурит Анна"
git push -q "$srv" main
cd / && rm -rf "$work"
# у студента: незаконченная правка в том же файле и черновик отчёта
cd "$dst"
sed -i 's/^сб  Лена$/сб  Студент/' schedule.txt
cp "$src/report-draft.txt" report.txt; chmod 644 report.txt

#!/bin/sh
# Собрать репозиторий расписания с ветками: данные из ./planner, правки по порядку, даты и авторы
# зафиксированы — хеши коммитов одинаковы на любой машине. Ветки export и dates уже влиты в main,
# notify — нет: она отросла от коммита «README: как пользоваться», и main с тех пор ушла вперёд.
# Запуск: mkrepo.sh <откуда-planner> <куда>
set -eu
src=$(cd "$1" && pwd) dst=$2
mkdir -p "$dst"
cp "$src"/README.md "$src"/schedule.txt "$dst"/
cd "$dst"
chmod 644 README.md schedule.txt                     # режим файла входит в хеш
git init -q -b main
day=0
when() {
    day=$((day + 1))
    d="2026-10-$(printf %02d "$day")T1$((day % 8)):1$((day % 6)):00+03:00"
    export GIT_AUTHOR_DATE="$d" GIT_COMMITTER_DATE="$d"
}
who() {  # who "Автор" "почта"
    export GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2"
}
c() { when; git add -A; git commit -q -m "$1"; }
m() { when; git merge -q --no-ff -m "$2" "$1"; }
anna() { who "Анна Смирнова" "anna@planner.school"; c "$1"; }
petr() { who "Пётр Ветров" "petr@planner.school"; c "$1"; }
oleg() { who "Олег Кузнецов" "oleg@planner.school"; c "$1"; }

anna "Первая версия расписания"
printf 'Ср 16:00 Шахматы    каб. 12\n' >> schedule.txt;                       oleg "Расписание: среда"

git switch -q -c export
cp "$src"/export.sh . && chmod 755 export.sh;                                 petr "Экспорт расписания в CSV"
sed -i 's/^echo "день;время;кружок;кабинет"$/echo "день;время;кружок;кабинет"  # заголовок для Excel/' export.sh
                                                                              petr "Экспорт: заголовок для Excel"
git switch -q main
who "Анна Смирнова" "anna@planner.school"; m export "Влила export: выгрузка в CSV"

git switch -q -c dates
sed -i 's/^Пн 15:00 Робототехника/Пн 15:30 Робототехника/' schedule.txt;      oleg "Робототехника на полчаса позже"
git switch -q main
who "Анна Смирнова" "anna@planner.school"; m dates "Влила dates: новое время робототехники"

cat "$src"/README.usage >> README.md;                                          anna "README: как пользоваться"

git switch -q -c notify
cp "$src"/notify.sh . && chmod 755 notify.sh;                                 petr "Напоминания за час до кружка"
sed -i 's/^quiet_from=23$/quiet_from=21/' notify.sh;                          petr "Напоминания: ночью тише"
git switch -q main

printf 'Пт 17:00 Театр      актовый зал\n' >> schedule.txt;                   oleg "Расписание: пятница"
cat "$src"/README.contacts >> README.md;                                       anna "README: контакты"

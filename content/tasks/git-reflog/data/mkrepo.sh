#!/bin/sh
# Собрать рукопись с историей — и «вчерашние» ошибки поверх: main откачен назад на три главы
# (reset --hard HEAD~3), ветка epilogue удалена (branch -D). Всё это помнит только журнал HEAD
# (reflog). Даты коммитов зафиксированы: потерянная вершина main — a07004d, вершина epilogue —
# c981d96 (их сверяет hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-$(printf %02d "$n")T2$((n % 4)):10:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
put() { cp "$src/novel/$1" "$1"; chmod 644 "$1"; }
put README.md;  c "Повесть «Дежурная»: замысел"
put glava-1.md; c "Глава 1"
put glava-2.md; c "Глава 2"
sed -i 's/как очередь за пельменями в пятницу/как очередь за пельменями в пятницу вечером/' glava-2.md; c "Глава 2: точнее"
put glava-3.md; c "Глава 3"
put glava-4.md; c "Глава 4"
git switch -q -c epilogue
put epilog.md;  c "Эпилог: черновик"
sed -i 's/навсегда остались/остались/' epilog.md; c "Эпилог: без пафоса"
git switch -q main
put glava-5.md; c "Глава 5"
put glava-6.md; c "Глава 6"
put glava-7.md; c "Глава 7"
git switch -q epilogue
sed -i 's/Аня закрыла ноутбук./Аня закрыла ноутбук и улыбнулась./' epilog.md; c "Эпилог: финальная фраза"
git switch -q main
# «вчера вечером»: хотел убрать одну главу, убрал три; заодно «прибрался» в ветках
git reset -q --hard HEAD~3
git branch -q -D epilogue

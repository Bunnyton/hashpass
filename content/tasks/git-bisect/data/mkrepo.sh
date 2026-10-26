#!/bin/sh
# Собрать историю калькулятора: 300 коммитов за год, тег v1.0 на первом. Почти все коммиты —
# правки меню и заметок; price.sh за это время переписывали шесть раз, и одна из этих правок
# (коммит 187) сломала округление скидки. Даты зафиксированы — виновник всегда один и тот же
# (fbb73db — его хеш сверяет Taskfile; вершина main — e5696a7).
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/calc/. "$dst"/
cd "$dst"
chmod 755 price.sh test.sh && chmod 644 README.md
printf 'Меню\n' > menu.txt && printf 'Заметки\n' > notes.txt
git init -q -b main
dishes="пельмени вареники манты хинкали равиоли галушки"
i=0
commit() {  # commit "сообщение"
    i=$((i + 1))
    case $((i % 3)) in
    0) name="Анна Смирнова" mail=anna@pelmen.shop ;;
    1) name="Пётр Ветров" mail=petr@pelmen.shop ;;
    *) name="Олег Кузнецов" mail=oleg@pelmen.shop ;;
    esac
    d=$(date -u -d "2025-11-01 +$((i - 1)) days +$((i % 12)) hours" +%Y-%m-%dT%H:%M:%S+00:00)
    git add -A
    GIT_AUTHOR_NAME="$name" GIT_AUTHOR_EMAIL="$mail" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$name" GIT_COMMITTER_EMAIL="$mail" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
commit "Калькулятор заказов 1.0"
git tag v1.0
while [ $i -lt 300 ]; do
    n=$((i + 1))
    case $n in
    41)  sed -i 's/^price=\$1$/price=$1     # рубли за штуку/' price.sh; commit "price.sh: комментарии" ;;
    97)  sed -i 's/^total=\$(( price \* count ))$/total=$(( count * price ))/' price.sh; commit "price.sh: порядок множителей как в ТЗ" ;;
    150) sed -i 's/^echo "\$total"$/printf "%s\\n" "$total"/' price.sh; commit "price.sh: printf вместо echo" ;;
    187) sed -i 's/^total=\$(( total - total \* discount \/ 100 ))$/total=$(( total - total \/ 100 * discount ))/' price.sh; commit "price.sh: скидка считается быстрее" ;;
    233) sed -i 's/^discount=\$3$/discount=${3:-0}/' price.sh; commit "price.sh: скидка необязательна" ;;
    271) sed -i 's/^# Сумма заказа:/# Сумма заказа (калькулятор «Пельменя»):/' price.sh; commit "price.sh: заголовок" ;;
    *)   if [ $((n % 2)) -eq 0 ]; then
             d=$(echo $dishes | tr ' ' '\n' | sed -n "$((n % 6 + 1))p")
             printf '%s — %s ₽\n' "$d" $((150 + n % 250)) >> menu.txt; commit "Меню: $d, позиция $n"
         else
             printf 'Заметка %s: обсудить с поставщиком партию №%s\n' "$n" $((n * 7 % 1000)) >> notes.txt; commit "Заметки: поставщик, партия $((n * 7 % 1000))"
         fi ;;
    esac
done

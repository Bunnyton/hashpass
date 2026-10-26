#!/bin/sh
# Собрать репозиторий бота: история из пяти коммитов (даты и автор зафиксированы — хеши одинаковы
# на любой машине), а поверх — НЕзакоммиченная работа над доставкой: правки в bot.sh и
# messages.txt и новый файл delivery.sh.
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/bot/. "$dst"/
cd "$dst"
chmod 755 bot.sh discount.sh && chmod 644 messages.txt README.md   # режим файла входит в хеш
git init -q -b main
n=0
c() {  # c "сообщение"
    n=$((n + 1))
    d="2026-10-0${n}T1${n}:15:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
git add -A
c "Бот: приветствие и цены"
printf '\nЗапуск: из каталога бота.\n' >> README.md;   c "README: как запускать"
sed -i 's/21:00 без выходных/21:00, в воскресенье до 18:00/' messages.txt; c "Часы работы в воскресенье"
sed -i 's/Не понимаю./Не понимаю, извините./' bot.sh;                  c "Вежливее, когда команда непонятна"
printf '    ./bot.sh hours            — часы работы и выходные\n' >> README.md; sed -i '/часы работы$/d' README.md; c "README: команда hours"
# незаконченная работа: доставка
sed -i 's/^    hours)   sed -n 2p "$here\/messages.txt" ;;$/&\n    delivery) echo "Доставка: $("$here\/delivery.sh" "$2") ₽. $(sed -n 3p "$here\/messages.txt")" ;;/' bot.sh
sed -i 's/hello, price, hours/hello, price, hours, delivery/' bot.sh
printf 'Привезём в течение двух часов.\n' >> messages.txt
cp "$src"/delivery.sh delivery.sh && chmod 755 delivery.sh

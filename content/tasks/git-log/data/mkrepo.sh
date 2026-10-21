#!/bin/sh
# Собрать репозиторий магазина с историей: данные из ./shop, правки по порядку, даты и авторы
# зафиксированы — хеши коммитов одинаковы на любой машине (виновник поломки — 6-й коммит).
# Запуск: mkrepo.sh <откуда-shop> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/. "$dst"/
cd "$dst"
chmod 644 app.conf README.md && chmod 755 deploy.sh   # режим файла входит в хеш
git init -q -b main
day=0
c() {  # c "Автор" "почта" "сообщение"
    day=$((day + 1))
    d="2026-09-$(printf %02d "$day")T1$((day % 8)):2$((day % 6)):00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.shop" "$1"; }
petr() { c "Пётр Ветров" "petr@pelmen.shop" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.shop" "$1"; }

anna "Первая версия конфигурации"
sed -i 's/^workers = 2/workers = 4/' app.conf;                oleg "Больше воркеров под распродажу"
printf 'Выкатка: ./deploy.sh из каталога репозитория.\n' >> README.md; anna "README: как выкатывать"
sed -i 's/^max_items = 50/max_items = 100/' app.conf;         anna "Корзина: до 100 товаров"
sed -i 's/^level = info/level = debug/' app.conf;             oleg "Логи подробнее — ловим баг с оплатой"
sed -i 's/^port = 8080/port = 80800/' app.conf;               petr "Обновил настройки"
printf 'echo "Готово."\n' >> deploy.sh;                        oleg "deploy.sh: сообщение в конце"
sed -i 's/^level = debug/level = info/' app.conf;             oleg "Баг с оплатой пойман, логи обратно"
printf '\n[promo]\ncode = PELMEN10\n' >> app.conf;            anna "Промокод на осень"
printf 'Дежурный в сентябре — Олег.\n' >> README.md;          anna "README: дежурный"
sed -i 's/^code = PELMEN10/code = PELMEN15/' app.conf;        petr "Промокод щедрее"
printf 'echo "Не забудь проверить сайт."\n' >> deploy.sh;      petr "deploy.sh: напоминание"
sed -i 's/^currency = RUB/currency = RUB\ndelivery = 300/' app.conf; anna "Доставка 300 рублей"
sed -i 's/^Дежурный в сентябре — Олег./Дежурный в октябре — Пётр./' README.md; oleg "README: дежурный в октябре"

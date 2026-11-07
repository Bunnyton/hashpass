#!/bin/sh
# Собрать ~/api: 40 коммитов четырёх авторов. В 19-м Пётр ради быстрых тестов поменял в общем
# config.ini timeout=30 на timeout=1, в 27-м Вася переформатировал весь конфиг (пробелы вокруг
# «=») — git blame на строке timeout показывает Васю. Даты фиксированы — хеши стабильны.
# Запуск: mkrepo.sh <репозиторий>
set -eu
dst=$1
mkdir -p "$dst" && cd "$dst"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d=$(date -u -d "2026-09-01 +$((n * 37)) hours" +%Y-%m-%dT%H:%M:00+00:00)
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.local" "$1"; }
petr() { c "Пётр Иванов" "petr@pelmen.local" "$1"; }
vasya() { c "Вася Пупкин" "vasya@pelmen.local" "$1"; }
log() { printf -- '- %s\n' "$1" >> CHANGELOG.md; }
route() { printf '%s\n' "$1" >> routes.txt; }
printf '# API доставки «Пельменя»\n\nЗапуск: ./api.sh, настройки — config.ini.\n' > README.md
printf '# Изменения\n\n' > CHANGELOG.md
anna "README"
cat > config.ini <<'INI'
[server]
host=0.0.0.0
port=8080
timeout=30
workers=4

[db]
host=db.pelmen.local
pool=10
INI
anna "Конфиг сервера"
printf 'GET /menu\n' > routes.txt; log "меню"; oleg "Маршрут: меню"
route "GET /menu/{id}"; log "блюдо по id"; oleg "Маршрут: блюдо"
sed -i 's/^workers=4$/workers=8/' config.ini; log "8 воркеров"; oleg "Больше воркеров"
route "POST /order"; log "заказ"; anna "Маршрут: заказ"
route "GET /order/{id}"; log "статус заказа"; anna "Маршрут: статус заказа"
printf '\nМаршруты — в routes.txt.\n' >> README.md; vasya "README: маршруты"
route "DELETE /order/{id}"; log "отмена заказа"; oleg "Маршрут: отмена"
route "GET /couriers"; log "курьеры"; petr "Маршрут: курьеры"
route "GET /zones"; log "зоны доставки"; petr "Маршрут: зоны"
sed -i 's/^pool=10$/pool=20/' config.ini; log "пул соединений 20"; anna "База: пул побольше"
route "POST /feedback"; log "отзывы"; vasya "Маршрут: отзывы"
route "GET /promo"; log "акции"; oleg "Маршрут: акции"
route "GET /health"; log "проверка живости"; petr "Маршрут: health"
route "GET /metrics"; log "метрики"; petr "Маршрут: метрики"
printf '\nТесты: ./test.sh\n' >> README.md; petr "README: тесты"
route "POST /login"; log "вход"; anna "Маршрут: вход"
sed -i 's/^timeout=30$/timeout=1/' config.ini; petr "Тесты: не ждать ответа по 30 секунд"
route "POST /logout"; log "выход"; anna "Маршрут: выход"
route "GET /profile"; log "профиль"; vasya "Маршрут: профиль"
route "PUT /profile"; log "правка профиля"; vasya "Маршрут: правка профиля"
route "GET /addresses"; log "адреса"; oleg "Маршрут: адреса"
route "POST /addresses"; log "новый адрес"; oleg "Маршрут: новый адрес"
route "GET /payments"; log "оплаты"; anna "Маршрут: оплаты"
sed -i 's/=/ = /' config.ini; vasya "Форматирование конфига: пробелы вокруг ="
route "POST /payments"; log "новая оплата"; anna "Маршрут: новая оплата"
route "GET /reviews"; log "отзывы списком"; vasya "Маршрут: отзывы списком"
route "GET /stats"; log "статистика"; petr "Маршрут: статистика"
sed -i 's/^port = 8080$/port = 8081/' config.ini; log "порт 8081"; oleg "Порт 8081: 8080 занят прокси"
route "GET /cart"; log "корзина"; anna "Маршрут: корзина"
route "POST /cart"; log "в корзину"; anna "Маршрут: в корзину"
route "DELETE /cart"; log "очистить корзину"; oleg "Маршрут: очистить корзину"
printf '\nЖалобы на долгие ответы — Олегу.\n' >> README.md; oleg "README: кому жаловаться"
route "GET /search"; log "поиск"; vasya "Маршрут: поиск"
route "GET /tags"; log "теги"; vasya "Маршрут: теги"
route "GET /news"; log "новости"; petr "Маршрут: новости"
log "релиз 1.4"; anna "Релиз 1.4"

#!/bin/sh
# Собрать репозиторий сайта: main и ветка release/1.0 (то, что сейчас работает у покупателей).
# После выпуска 1.0 в main ушло девять коммитов: новые функции и среди них одно исправление
# уязвимости в upload.sh (имя файла с ../ писало за пределы uploads). Даты зафиксированы:
# исправление — коммит 92e5d2b, вершина release/1.0 — 77348e5, main — c00b822 (их сверяет hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/app/. "$dst"/
cd "$dst"
chmod 755 upload.sh && chmod 644 VERSION menu.txt .gitignore
git init -q -b main
n=0
c() {  # c "Автор" "почта" "сообщение"
    n=$((n + 1))
    d="2026-09-$(printf %02d $((n + 3)))T1$((n % 9)):40:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.shop" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@pelmen.shop" "$1"; }
petr() { c "Пётр Ветров" "petr@pelmen.shop" "$1"; }
anna "Сайт: меню и загрузка файлов"
printf 'Манты — 299 ₽\n' >> menu.txt;                          oleg "Меню: манты"
# выпуск 1.0 — отдельная ветка, в ней только номер версии
git switch -q -c release/1.0
echo 1.0 > VERSION;                                           anna "Версия 1.0"
git switch -q main
printf 'Хинкали — 329 ₽\n' >> menu.txt;                        oleg "Меню: хинкали"
printf '#!/bin/sh\n# Корзина: ./cart.sh <товар> — добавить\necho "$1" >> "$(dirname "$0")/cart.txt"\n' > cart.sh; chmod 755 cart.sh
                                                              petr "Корзина (черновик, не для покупателей)"
sed -i 's/^Пельмени домашние — 349 ₽$/Пельмени домашние — 359 ₽/' menu.txt; anna "Пельмени подорожали"
sed -i 's/^name=\$1$/name=$(basename "$1")   # только имя: без каталогов и ..\//' upload.sh
                                                              petr "upload.sh: имя файла без каталогов — нельзя записать за пределы uploads"
printf 'echo "Итого в корзине: $(wc -l < "$(dirname "$0")/cart.txt")"\n' >> cart.sh; petr "Корзина: итог"
echo 1.1-dev > VERSION;                                       anna "Начали 1.1"
printf 'Сметана 20%% — 99 ₽\n' >> menu.txt;                    oleg "Меню: сметана"
sed -i 's/сохранено: \$name/сохранено: $name ($(wc -c < "$dir\/$name") байт)/' upload.sh; petr "upload.sh: размер в ответе"
printf 'Аджика — 159 ₽\n' >> menu.txt;                          oleg "Меню: аджика"

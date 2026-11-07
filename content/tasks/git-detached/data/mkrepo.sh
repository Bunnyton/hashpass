#!/bin/sh
# Собрать ~/booking: релиз v1.0 (тег), после него в main ещё пять коммитов. Студент «вчера»
# встал на v1.0 (git checkout v1.0 — detached HEAD) и сделал там два коммита-исправления:
# консоль начинается прямо в этом состоянии. Даты фиксированы — хеши стабильны (hp/state).
# Запуск: mkrepo.sh <репозиторий>
set -eu
dst=$1
mkdir -p "$dst" && cd "$dst"
git init -q -b main
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-$((10 + n))T1$((n % 10)):45:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@pelmen.local" "$1"; }
me()   { c "Студент" "student@hashpass.local" "$1"; }
printf '# Бронь столиков «Пельменя»\n\n./book.sh <дата ГГГГ-ММ-ДД> <гостей>\n' > README.md
cat > book.sh <<'SH'
#!/bin/sh
# Бронь столика: ./book.sh 2026-12-31 4
day=$1 guests=$2
[ -n "$guests" ] || { echo "Использование: ./book.sh <дата> <гостей>" >&2; exit 2; }
when=$(date -d "$day" +%d.%m 2>/dev/null) || { echo "Не понял дату: $day" >&2; exit 1; }

# зал: 12 столиков, банкетный — по звонку
[ "$guests" -ge 1 ] || { echo "Гостей должно быть хотя бы 1" >&2; exit 1; }
[ "$guests" -le 8 ] || { echo "Больше 8 гостей — звоните администратору" >&2; exit 1; }
echo "Столик на $guests, $when — забронирован"
SH
chmod 755 book.sh
cat > test.sh <<'SH'
#!/bin/sh
# Проверки брони: ./test.sh
ok=0
t() { out=$(./book.sh "$1" "$2" 2>&1); case "$out" in *"$3"*) ;; *) echo "ПРОВАЛ: $1 $2 → $out"; ok=1 ;; esac; }
t 2026-12-31 4 "31.12"
t 2026-01-07 2 "07.01"
t 2026-12-31 9 "администратору"
exit $ok
SH
chmod 755 test.sh
anna "Бронь столиков"
GIT_COMMITTER_NAME="Анна Смирнова" GIT_COMMITTER_EMAIL="anna@pelmen.local" \
    GIT_COMMITTER_DATE="2026-10-11T12:00:00+03:00" git tag -a v1.0 -m "Версия 1.0"
printf '\nЗал: 12 столиков, банкетный — по звонку.\n' >> README.md; anna "README: зал"
printf 'Пн–Вс 11:00–23:00\n' > hours.txt; anna "Часы работы"
sed -i 's/^\[ "\$guests" -le 8 \]/[ "$guests" -le 10 ]/; s/Больше 8 гостей/Больше 10 гостей/' book.sh
sed -i 's/^t 2026-12-31 9 /t 2026-12-31 11 /' test.sh; anna "Бронь: до 10 гостей"
printf 'Пт–Сб до 01:00\n' >> hours.txt; anna "Часы: пятница и суббота"
printf '\nОтмена брони — за 2 часа.\n' >> README.md; anna "README: отмена"
main=$(git rev-parse HEAD)
# вчера: студент встал на v1.0 и починил там бронь на «завтра» и «сегодня»
git -c advice.detachedHead=false checkout -q v1.0
sed -i 's/^when=\$(date -d "\$day"/case "$day" in сегодня) day=today ;; завтра) day=tomorrow ;; esac\nwhen=$(date -d "$day"/' book.sh
me "Бронь: «сегодня» и «завтра» вместо даты"
printf 't завтра 2 "забронирован"\n' > t.add
sed -i '/^t 2026-12-31 4 /r t.add' test.sh && rm t.add
me "Тест: бронь на завтра"

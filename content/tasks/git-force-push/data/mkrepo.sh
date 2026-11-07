#!/bin/sh
# Собрать «сервер» каталога книжного и клон студента. Ветка search (студент, два коммита)
# уже на сервере; утром студент перестроил её поверх свежего main (rebase), а Олег после
# этого отправил в search свой коммит — студент о нём не знает (fetch не делал).
# Даты и авторы зафиксированы — хеши одни на любой машине (их сверяет hp/state).
# Запуск: mkrepo.sh <сервер.git> <клон>
set -eu
srv=$1 dst=$2
work=$(mktemp -d)
cd "$work"
git init -q -b main
n=0
at() { n=$((n + 1)); d="2026-11-$((10 + n))T1$((n % 10)):30:00+03:00"; }
c() {  # c "имя" "почта" "сообщение"
    at
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
anna() { c "Анна Смирнова" "anna@books.local" "$1"; }
oleg() { c "Олег Кузнецов" "oleg@books.local" "$1"; }
me()   { c "Студент" "student@hashpass.local" "$1"; }
printf '# Каталог книжного «Переплёт»\n' > README.md; anna "README"
cat > books.txt <<'TXT'
Мастер и Маргарита;Булгаков;650
Пикник на обочине;Стругацкие;420
Понедельник начинается в субботу;Стругацкие;480
Собачье сердце;Булгаков;390
Идиот;Достоевский;560
TXT
anna "Каталог"
git switch -q -c search
cat > search.sh <<'SH'
#!/bin/sh
# Поиск по каталогу: ./search.sh <слово> — книги, где оно есть в названии или авторе.
grep -- "$1" books.txt
SH
chmod 755 search.sh; me "Поиск по каталогу"
printf '\nПоиск: ./search.sh Булгаков\n' >> README.md; me "README: поиск"
git switch -q main
printf 'Град обреченный;Стругацкие;510\n' >> books.txt; anna "Каталог: Град обреченный"
sed -i 's/^Идиот;Достоевский;560$/Идиот;Достоевский;590/' books.txt; anna "Идиот подорожал"
git clone -q --bare "$work" "$srv"
git -C "$srv" config uploadpack.allowAnySHA1InWant true
git clone -q "$srv" "$dst"
# студент перестраивает search поверх main (ещё не отправил)
cd "$dst"
git switch -q search
at
GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
    git rebase -q main
# Олег тем временем дописывает в search на сервере (студент не делал fetch)
cd "$work"
git switch -q search
sed -i 's/grep -- "\$1" books.txt/grep -i -- "$1" books.txt/' search.sh
sed -i 's/^# Поиск по каталогу: .*/# Поиск по каталогу: .\/search.sh <слово> — без учёта регистра./' search.sh
oleg "Поиск: регистр не важен"
git push -q "$srv" search
cd / && rm -rf "$work"

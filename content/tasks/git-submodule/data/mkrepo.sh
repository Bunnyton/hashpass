#!/bin/sh
# Собрать два «серверных» репозитория: движок engine.git и игру game.git, в которой движок —
# подмодуль engine/ (закреплён на первой версии). Клон игры у студента — без --recurse:
# каталог engine/ пустой. Даты фиксированы — хеши стабильны (hp/state).
# Запуск: mkrepo.sh <каталог-серверов> <клон-игры>
set -eu
srv=$1 dst=$2
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-10-$((10 + n))T1$((n % 10)):05:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
oleg() { c "Олег Кузнецов" "oleg@games.local" "$1"; }
anna() { c "Анна Смирнова" "anna@games.local" "$1"; }
e=$(mktemp -d) && cd "$e" && git init -q -b main
cat > engine.sh <<'SH'
#!/bin/sh
# Движок «Пельмень-квест»: engine_room <название> <описание> — показать комнату.
ENGINE_VERSION=1.0
engine_room() { printf '\n== %s ==\n%s\n' "$1" "$2"; }
SH
oleg "Движок 1.0"
git clone -q --bare "$e" "$srv/engine.git"
g=$(mktemp -d) && cd "$g" && git init -q -b main
cat > play.sh <<'SH'
#!/bin/sh
# Пельмень-квест: ./play.sh
cd "$(dirname "$0")"
. ./engine/engine.sh
engine_room "Кухня" "Пахнет тестом. На столе — скалка."
engine_room "Холодильник" "Фарш ждёт своего часа."
echo "(движок $ENGINE_VERSION)"
SH
chmod 755 play.sh
printf '# Пельмень-квест\n\nЗапуск: ./play.sh\n' > README.md
anna "Игра: две комнаты"
git -c protocol.file.allow=always submodule add -q "$srv/engine.git" engine
anna "Движок — подмодулем"
git clone -q --bare "$g" "$srv/game.git"
cd /
rm -rf "$e" "$g"
git clone -q "$srv/game.git" "$dst"

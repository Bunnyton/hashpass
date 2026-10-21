#!/bin/sh
# «Сервер» команды: голый репозиторий с историей из ./team. Запуск: mkrepo.sh <откуда-team> <куда.git>
set -eu
src=$1 dst=$2
work=$(mktemp -d)
cp -r "$src"/. "$work"/
cd "$work"
chmod 755 bot.sh
git init -q -b main
export GIT_AUTHOR_NAME="Анна Смирнова" GIT_AUTHOR_EMAIL="anna@duty.bot"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git add . && git commit -q -m "Бот дежурств: первая версия"
git clone -q --bare "$work" "$dst"
rm -rf "$work"

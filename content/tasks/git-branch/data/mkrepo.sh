#!/bin/sh
# Репозиторий сайта кофейни: два коммита в main. Запуск: mkrepo.sh <откуда-site> <куда>
set -eu
src=$1 dst=$2
mkdir -p "$dst"
cp -r "$src"/. "$dst"/
cd "$dst"
git init -q -b main
export GIT_AUTHOR_NAME="Анна Смирнова" GIT_AUTHOR_EMAIL="anna@byte.cafe"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git add index.html && git commit -q -m "Главная страница"
git add style.css && git commit -q -m "Стили"
# коллега отправляет сюда свои коммиты, пока студент работает в ветке
git config receive.denyCurrentBranch updateInstead

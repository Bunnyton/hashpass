#!/bin/sh
# Собрать ~/calc: три коммита, а в рабочем каталоге — две правки вперемешку: исправление
# деления на ноль (готово) и недописанная степень (^). В calc.sh они в разных кусках, в
# README.md — в одном куске через строку (его делят на части). Хеши стабильны (hp/state).
# Запуск: mkrepo.sh <каталог-с-data> <репозиторий>
set -eu
src=$1/calc dst=$2
mkdir -p "$dst" && cd "$dst"
git init -q -b main
n=0
c() {
    n=$((n + 1))
    d="2026-11-0$n""T1$n:10:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
cp "$src/calc.sh" calc.sh && chmod 755 calc.sh
sed -i '/^    x)/d; s/^# Калькулятор: .*/# Калькулятор: .\/calc.sh 12 + 5/; s/Операции: + - x \//Операции: + - \//' calc.sh
c "Калькулятор: сложение, вычитание, деление"
cp "$src/calc.sh" calc.sh; c "Калькулятор: умножение"
cp "$src/README.md" README.md; c "README"
cp "$src/calc-full.sh" calc.sh
cp "$src/README-full.md" README.md

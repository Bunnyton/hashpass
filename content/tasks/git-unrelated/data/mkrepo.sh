#!/bin/sh
# Собрать ~/blog (три коммита студента, своя история с git init) и «сервер» blog.git, который
# коллега создал через веб-интерфейс с README.md и LICENSE — первый коммит у каждого свой.
# README.md есть в обоих — при слиянии будет конфликт «add/add». Хеши стабильны.
# Запуск: mkrepo.sh <сервер.git> <блог>
set -eu
srv=$1 dst=$2
n=0
c() {  # c "имя" "почта" "сообщение"
    n=$((n + 1))
    d="2026-11-0$n""T1$n:40:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="$1" GIT_COMMITTER_EMAIL="$2" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$3"
}
me() { c "Студент" "student@hashpass.local" "$1"; }
work=$(mktemp -d)
cd "$work"
git init -q -b main
cat > README.md <<'TXT'
# Блог «Пельменная кухня»

Рецепты и истории с кухни.
TXT
cat > LICENSE <<'TXT'
MIT License

Copyright (c) 2026 Пельменная кухня

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
TXT
c "Анна Смирнова" "anna@pelmen.local" "Initial commit"
git clone -q --bare "$work" "$srv"
cd / && rm -rf "$work"
mkdir -p "$dst" && cd "$dst"
git init -q -b main
mkdir posts
cat > README.md <<'TXT'
# Блог о пельменях

Как собрать: ./build.sh — склеит посты в index.html.
TXT
cat > build.sh <<'SH'
#!/bin/sh
# Склеить посты из posts/ в index.html.
{ echo '<h1>Пельменная кухня</h1>'; for p in posts/*.txt; do echo "<pre>$(cat "$p")</pre>"; done; } > index.html
echo "index.html: $(ls posts/*.txt | wc -l) пост(ов)"
SH
chmod 755 build.sh
printf 'Тесто для пельменей\n\nМука, вода, яйцо, соль. Замесить и дать отдохнуть 30 минут.\n' > posts/01-testo.txt
me "Блог: сборка и первый пост"
printf 'Фарш\n\nГовядина и свинина пополам, лук, перец, ледяная вода.\n' > posts/02-farsh.txt
me "Пост: фарш"
printf 'Лепка\n\nКружок, ложка фарша, края — щепоткой.\n' > posts/03-lepka.txt
me "Пост: лепка"

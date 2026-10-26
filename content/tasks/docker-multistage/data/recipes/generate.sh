#!/bin/sh
# Сайт рецептов: из pages/*.txt (первая строка — заголовок, дальше текст) делает /www —
# страницу на каждый рецепт и оглавление index.html. Шаблон берёт из инструментов /opt/tools.
set -e
tpl=/opt/tools/templates/page.html
[ -f "$tpl" ] || { echo "нет инструментов генератора: $tpl" >&2; exit 1; }
src=$(dirname "$0")/pages
mkdir -p /www
echo '<!doctype html><meta charset="utf-8"><title>Рецепты «Пельменя»</title><h1>Рецепты «Пельменя»</h1><ul>' > /www/index.html
for f in "$src"/*.txt; do
    name=$(basename "$f" .txt)
    title=$(sed -n 1p "$f")
    text=$(sed -n '2,$p' "$f")
    sed -e "s|{{title}}|$title|g" -e "s|{{text}}|$text|g" "$tpl" > "/www/$name.html"
    echo "<li><a href=\"$name.html\">$title</a></li>" >> /www/index.html
done
echo '</ul>' >> /www/index.html
echo "сайт готов: $(ls /www | wc -l) файлов"

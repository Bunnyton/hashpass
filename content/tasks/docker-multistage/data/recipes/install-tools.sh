#!/bin/sh
# Инструменты генератора сайта: шаблон страницы и пакет шрифтов для превью (~60 МБ).
# Нужны только во время сборки сайта — сам сайт их не использует.
set -e
echo "ставлю инструменты генератора…"
mkdir -p /opt/tools/templates /opt/tools/fonts
cat > /opt/tools/templates/page.html <<'HTML'
<!doctype html><meta charset="utf-8"><title>{{title}} — Рецепты «Пельменя»</title>
<p><a href="index.html">← все рецепты</a></p><h1>{{title}}</h1><p>{{text}}</p>
HTML
for f in regular bold italic; do
    dd if=/dev/urandom of=/opt/tools/fonts/pelmen-$f.bin bs=1M count=20 2>/dev/null
done
echo "инструменты готовы: $(du -sh /opt/tools | cut -f1)"

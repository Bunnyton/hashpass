#!/bin/sh
# Блог: страница собирается при старте из переменных окружения TITLE и ADMIN_PASSWORD.
admin="выключена"
[ -n "$ADMIN_PASSWORD" ] && admin="включена"
mkdir -p /www
cat > /www/index.html <<HTML
<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>${TITLE:-Без названия}</title></head>
<body>
<h1>${TITLE:-Без названия}</h1>
<p>Записки повара: рецепты, закупки, новости кухни.</p>
<p>Админка: $admin</p>
</body></html>
HTML
echo "blog: «${TITLE:-Без названия}», админка $admin"
exec httpd -f -p 80 -h /www

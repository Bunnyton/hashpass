#!/bin/sh
# Файловый сервис: при старте отдаёт каталог /data пользователю nobody и раздаёт его по HTTP.
chown -R nobody:nobody /data || exit 1
echo "files: /data отдан пользователю nobody, раздаю на порту 80"
exec httpd -f -p 80 -h /data

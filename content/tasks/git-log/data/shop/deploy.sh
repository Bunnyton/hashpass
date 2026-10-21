#!/bin/sh
# Выкатить конфигурацию на сервер
set -e
echo "Проверяю app.conf..."
grep -q '^port = ' app.conf
echo "Выкатываю..."

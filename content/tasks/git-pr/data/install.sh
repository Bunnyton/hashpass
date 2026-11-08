#!/bin/sh
# Поставить Лепку: сайт, конфиг, бота задания, службу на 127.0.0.1:8930, каталог данных.
# Запуск: install.sh <каталог-с-data>
set -eu
src=$1
install -D -m 755 "$src/lepka/lepka.py" /usr/local/lib/lepka/lepka.py
install -D -m 755 "$src/lepka/post-receive" /usr/local/lib/lepka/post-receive
install -D -m 755 "$src/lepka/pre-receive" /usr/local/lib/lepka/pre-receive
install -m 644 "$src/bot.py" /usr/local/lib/lepka/bot.py
install -m 644 "$src/lepka.json" /etc/lepka.json
install -m 644 "$src/system/lepka.service" /etc/systemd/system/lepka.service
rm -rf /var/lib/lepka && install -d -o student -g student /var/lib/lepka
systemctl enable lepka.service

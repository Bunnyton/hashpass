#!/bin/sh
# Архив домашнего каталога в /var/backups с датой в имени
set -e
dest=/var/backups/home-$(date +%F).tar.gz
tar -czf "$dest" -C /home "$USER"
echo "Готово: $dest"

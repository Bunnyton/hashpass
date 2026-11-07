#!/bin/sh
# Резервная копия сайта в /var/backups/site
set -e
dst=/var/backups/site/$(date +%F)
mkdir -p "$dst"
cp -r ./* "$dst"/
echo "Копия: $dst"

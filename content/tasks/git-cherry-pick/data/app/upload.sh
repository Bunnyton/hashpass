#!/bin/sh
# Сохранить загруженный файл: ./upload.sh <имя> < содержимое
dir=$(dirname "$0")/uploads
mkdir -p "$dir"
name=$1
cat > "$dir/$name"
echo "сохранено: $name"

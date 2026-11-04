#!/bin/bash
# Чистит кэш сборки. Пока только показывает, что удалил бы: rm включим, когда список будет верным.
CACHE_DIR=~/broken/cache

for f in "$CAHCE_DIR"/*; do
    echo "удаляю: $f"
    # rm -rf "$f"
done

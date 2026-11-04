#!/bin/bash
# Сводка по выгрузкам: сколько строк в каждом CSV и всего.
total=0
for f in ~/broken/data/*.csv; do
    n=$(wc -l < "$f")
    echo "$(basename "$f"): $n"
    total=$((total + n))
done
echo "Всего строк: $total"

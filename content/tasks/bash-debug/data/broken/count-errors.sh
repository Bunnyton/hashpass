#!/bin/bash
# Сколько строк с ERROR во всех журналах ~/broken/logs.
count=0
for f in ~/broken/logs/*.log; do
    cat "$f" | while read -r line; do
        if [[ $line == *ERROR* ]]; then
            count=$((count + 1))
        fi
    done
done
echo "Ошибок: $count"

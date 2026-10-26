#!/bin/sh
# Отчёт по продажам: ./report.sh [файл] — выручка по месяцам и лучший товар квартала.
f=${1:-$(dirname "$0")/sales.csv}
echo "Выручка по месяцам, ₽:"
tail -n +2 "$f" | awk -F';' '{ m = substr($1, 1, 7); sum[m] += $3 * $4 } END { for (m in sum) print "  " m ": " sum[m] }' | sort
echo "Лучший товар квартала:"
tail -n +2 "$f" | awk -F';' '{ n[$2] += $3 } END { for (g in n) print n[g] ";" g }' | sort -t';' -k1,1nr | head -1 | awk -F';' '{ print "  " $2 " — " $1 " шт." }'

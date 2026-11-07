#!/bin/sh
# Кто дежурит сегодня: ./duty.sh [день]
day=${1:-$(LC_TIME=ru_RU.UTF-8 date +%a | cut -c1-2)}
awk -v d="$day" '$1 == d { print "Дежурит: " $2 }' schedule.txt

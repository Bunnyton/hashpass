#!/bin/sh
# Напомнить о кружке за час до начала
quiet_from=23
hour=$(date +%H)
[ "$hour" -ge "$quiet_from" ] && exit 0
grep "^$(LC_TIME=ru_RU.UTF-8 date +%a | cut -c1-2)" schedule.txt

#!/bin/sh
# Выгрузить расписание в CSV для Excel
echo "день;время;кружок;кабинет"
sed 's/  */;/g' schedule.txt

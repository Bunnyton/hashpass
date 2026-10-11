#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [[ -z "$(diff edit.txt true.txt)" ]]
then
	echo "Чисто. Ни одной лишней буквы — ты справился с vim!"
else
	echo "Внимательнее, салага!"
fi

#!/bin/sh
# Удалить из /tmp файлы старше недели
find /tmp -type f -mtime +7 -print -delete

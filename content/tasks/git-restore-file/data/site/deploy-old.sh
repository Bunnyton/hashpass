#!/bin/sh
# Выкладка через FTP — больше не используется
ftp -n pelmen.example <<END
user admin admin
put index.html
END

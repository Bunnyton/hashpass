#!/bin/fish

set GREEN "\033[01;32m"
set RESET "\033[0;0m"
set BLUE "\033[01;34m"
set WHITE "\033[01;97m"

# while true

set TIME (date +'%H:%M:%S')
set CURDIR (echo $PWD | sed -e "s;^$HOME;\~;")

set -l PROMPT (echo -e "$GREEN$USER@$HOSTNAME $RESET in $BLUE$CURDIR$RESET\n[$TIME]$WHITE ξ $RESET")
read -S -P "$PROMPT" cmd
set -g CMD "$cmd"
# bash -c "script -qfc \"$cmd\" log.txt"

# end

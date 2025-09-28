#!/bin/bash

if [[ -f "/.hash/bin/shell.py" ]]
then
	python3 /.hash/bin/shell.py "$@"

elif [[ "$1" == "task" && "$2" == "exit" && -z "$3" ]]
then
	echo "stopping" >> /.hash/.hash.status
else
	echo "Invalid commands"
fi

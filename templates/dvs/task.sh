#!/bin/bash

if [[ -f "/.hash/bin/taskclient.py" ]]
then
	python3 /.hash/bin/taskclient.py "$@"

elif [[ "$@" == "task exit" ]]
then
	echo "stopping" > /.hash/.hash.status

else
	echo "Invalid command"
fi

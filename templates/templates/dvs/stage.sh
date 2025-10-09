#!/bin/bash

if [[ -f "/.hash/bin/taskclient.py" ]]
then
        python3 /.hash/bin/taskclient.py stage "$@"
else
	echo "Invalid command"
fi

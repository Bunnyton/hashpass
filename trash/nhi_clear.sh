#!/bin/bash -i

set -x
sessions=$(nhi log | grep -i session | awk '{print $3}' | sort)

head=$(echo "$sessions" | head -1)
last=$(echo "$sessions" | tail -1)

nhi remove $head:$last

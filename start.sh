#!/bin/bash

mkdir ./test 2> /dev/null
mkdir ./work 2> /dev/null

sudo mount overlay -t overlay -o lowerdir=./lib/images/debootstrap/debian-stable/,upperdir=./lib/images/base/student-debian,workdir=./work ./test

sudo ./start_nspawn.sh

sudo umount ./test 
sleep 2

if [ `ls -a test | wc -l` -eq 2 ]
then
	rm -rf test 
	rm -rf work 
fi

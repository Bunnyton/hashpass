#!/bin/bash

if [[ $(whoami) != "root" && $EUID -ne 0 ]]
then
    echo "Скрипт должен иметь права суперпользователя, пожалуйста, воспользуйтесь sudo"
    exit 1
fi

if [ ! -d lib/images/debootstrap ]
then
	mkdir lib/images/debootstrap
fi

if [ `ls -a lib/images/debootstrap | wc -l` -eq 2 ]
then
	cd lib/images/debootstrap
	debootstrap stable ./debian-stable http://mirror.yandex.ru/debian
	cd -
fi


mkdir ./test 2> /dev/null
mkdir ./work 2> /dev/null

mount overlay -t overlay -o lowerdir=./lib/images/debootstrap/debian-stable/,upperdir=./lib/images/base/student-debian,workdir=./work ./test

sleep 5

./start_nspawn.sh

umount ./test 
sleep 2

if [ `ls -a test | wc -l` -eq 2 ]
then
	rm -rf test 
	rm -rf work 
fi

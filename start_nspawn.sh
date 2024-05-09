#!/bin/bash

sudo systemd-nspawn -b -q -D ./lib/images/debootstrap/debian-stable --user student --overlay="$PWD/lib/images/debootstrap/debian-stable:$PWD/lib/images/base/student-debian:/" script -q -c bash /var/log/hashpass.log


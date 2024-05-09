#!/bin/bash

sudo systemd-nspawn -q --boot -D ./lib/images/debootstrap/debian-stable --user student --overlay="$PWD/lib/images/debootstrap/debian-stable:$PWD/lib/images/base/student-debian:/" 

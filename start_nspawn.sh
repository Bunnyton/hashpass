#!/usr/bin/expect -f



spawn systemd-nspawn -b -q \
	-D ./test \
	--user root # \
	# sudo script -q -c 'sudo -u student bash' /var/log/hashpass.log
	# -D ./lib/images/debootstrap/debian-stable \
	# --overlay="$PWD/lib/images/debootstrap/debian-stable:$PWD/lib/images/base/student-debian:/" \

expect "login" { send "student\r" }
expect "Password" { send "student\r" }

interact 


#!/usr/bin/expect -f



spawn systemd-nspawn -b -q \
	-D ./test \
	--user root \
	sudo script -fc 'sudo -u student bash' /var/log/hashpass.log
	# -D ./lib/images/debootstrap/debian-stable \
	# --overlay="$PWD/lib/images/debootstrap/debian-stable:$PWD/lib/images/base/student-debian:/" \

expect "login" { send "root\r" }
expect "Password" { send "root\r" }
expect "root@" { send "script -fc 'sudo -u student bash' /var/log/hashpass.log; shutdown now\r" }
expect "@" { send "clear\r" }

interact 


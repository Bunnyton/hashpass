ls
exit
ls
vim ~/.bashrc 
ls
ls -la
vim ~/.bashrc
ls
exit
ls
ls -al
vim ~/.bashrc
ls
exit
chmod +wr /var/log/script.log
sudo chmod +wr /var/log/script.log
exit
vim ~/.bashrc
ls
exit
ls
exit
ls
script /var/log/hashpass.log
ls
vim ~/.bashrc
script /var/log/hashpass.log
ls
script --help
script -c bash /var/log/hashpass.log
exit
ls -la
ls
ls 
vim .bashrc
ls
ls -a
mkdir /etc/hashpass
sudo mkdir /etc/hashpass
groups
ls
exit
ls
vim ~/.bashrc
ls
ls -la
vim .bashrc
ls
ls -la
ls
cp .bashrc .hashpass
mv .hashpass .hashpassrc
ls
vim .hashpassrc 
vim .bashrc 
ls
source ~/.bashrc
exit
exti
exit
ls
exit
ls
cd home/
ls
exit
cd ~
ls
vim .bashrc
ls
exit
ls
exit
ls
ls -al
exit
ls
ls -a
cd ~
ls
ls -la
vim .bashrc
ls
exit
ls
ls -la
exit
ls
vim .bashrc
sudo chown -R student ./
sudo chgrp -R student ./
ls
vim .bashrc
source ~/.bashr
source ~/.bashrc
exit
ls
exit
ls
vim .bashrc
unalias exit
exit
ls
ls 
la
ls -a
unalias exit
root@
exit 
ls
ls -a
exit
unalias exit
exit
clear
ls
ls -la
unalias exit
exit
clear
ls
ls -a
ls -la
vim .bashrc
ls
unalias exit
exit
history
exit
id
chown -R student /home/student
sudo chown -R student /home/student
ls
ls -la
sudo chown -R student ./
exit
sudo apt update
exit
sudo apt update
ls -l /etc/sudo.conf 
chmod 440 /etc/sudo.conf
sudo chmod 440 /etc/sudo.conf
sudo apt update
exit
sudo shutdown now
clear
ls -la
vim /var/log/hashpass.log 
cat /var/log/hashpass.log 
2RR65;6800;1c10;rgb:9494/a3a3/a5a511;rgb:2828/2a2a/363611;rgb:2828/2a2a/363611;rgb:2828/2a2a/363611;rgb:2828/2a2a/3636
clear
ls
exit
clear
ls
ls -al
ps 
ps -e
vim ~/.bashrc
source ~/.bashrc
ls
ls -la
echo $TERM
vim ~/.bashrc
apt install tput
sudo apt install tput
ls
ls -la
bash
hash
sudo chmod +x /usr/bin/hash
bash
hash
exit
ls
ls -l
clear
exit
clear
ls
ls -la
fish
exit
clear
ls
alias
bash 
vim /usr/bin/hash
fish 
sudo apt install script
clear
ls
vim ~/.bashrc
exit
exit
ls
clear
ls -la
clear
vim hash
sudo vim ./hash 
cd /usr/bin/
ls
vim ./hash 
exit
ls
clear
ls
./hash
vim hash
exit
sudo vim ./hash
pwd
cd ~
ls
sudo vim /usr/bin/hash
exit
read --help
exit
ls
ls -la
exit
ls
ls -la
exit
ls
omf install https://github.com/jhillyerd/plugin-git
apt install omf
sudo apt install omf
curl -L https://get.oh-my.fish | fish
sudo apt install curl
curl -L https://get.oh-my.fish | fish
exit
ls
pwd
exit
ls
pwd
cd /usr/
pwd
exit
exit
pwd
cd /usr/
pwd
ls
exit
pwd
ls -la
ls
sudo vim /etc/bash.bashrc 
bash -c "ls"
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
# bind 'set'
# bind 'set show-all-if-ambiguous on'
# bind 'TAB:menu-complete'
# # bind -o default
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
bash -c "ls -la"
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
# bind 'set'
# bind 'set show-all-if-ambiguous on'
# bind 'TAB:menu-complete'
# # bind -o default
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
exit
#!/bin/bash -i
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
# bind 'set'
# bind 'set show-all-if-ambiguous on'
# bind 'TAB:menu-complete'
# # bind -o default
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
alias
bash --help
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
# bind 'set'
# bind 'set show-all-if-ambiguous on'
# bind 'TAB:menu-complete'
# # bind -o default
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
clera
clear
ls
ls -la
ls --help
ls --help | less
ls
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
# bind 'set'
# bind 'set show-all-if-ambiguous on'
# bind 'TAB:menu-complete'
# # bind -o default
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
cd /usr/bin/
sudo ./hash
./hash
rm /tmp/.hashpass_cmd*
sudo rm /tmp/.hashpass_cmd*
./hash
fish
clear
ls
ls -la
hash
cd /usr/bin/
ls
ls | grep hash
./hash
chmod +x hash
sudo chmod +x ./hash
./hash 
ls hash
./hash
vim hash
sudo vim hash
bash
./hash
vim ./hash
sudo vim ./hash
./hash 
ls -l hash
./hash
./bash hash
vim ~/.hash
vim hash
sudo vim hash
./hash
vim hash 
sudo vim hash
./hash
ls
vim hash
sudo vim hash
./hash
sudo vim ./hash
./hash
ls
sudo vim ./hash
./hash
sudo vim hash
./hash
sudo vim hash
./ahsh
./hash
sudo vim hash
unalias bash
alias
ll
hash
cd /usr/bin/
which hash
hash
./hash
bash hash
bash -i hash
bash
bash
s
bash
clear
ls
alias
exit
clear
ls 
,.
clera
clear
history 
history | grep history 
history | grep ls
clear
grep --help
vim usr/bin/bash.bashrc
sudo vim /etc/bash.bashrc 
exit
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
signals=$(kill -l)
trap '' SIGINT SIGTERM SIGHUP SIGQUIT SIGABRT SIGKILL SIGSTOP 2> /dev/null
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi
ls
sudo vim /usr/bin/hash
bash
exit
clear
exit
clear
ls
ls -la
clear
ll
la
history | grep history
celar
clear
ls
cat /usr/bin/hash
ls
clear
exit
#!/bin/bash
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
cmdfile="/tmp/.hashpass_cmd"
logfile="/tmp/.hashpass_cmd.out"
signals=$(kill -l)
trap '' SIGINT SIGTERM SIGHUP SIGQUIT SIGABRT SIGKILL SIGSTOP 2> /dev/null
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	touch $cmdfile $logfile; 	chmod +wr $cmdfile $logfile; 	while [ 0 -eq 0 ]; 	do 		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $cmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $cmdfile"; 		cmd=$(cat $cmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $logfile; 
	done; fi

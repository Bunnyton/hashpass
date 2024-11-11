exit
ls
ls
bash
exit
ls
su - debian
su debian
users
exit
passwd
exit
apt update
apt install python3
ls
task stop
cat /.hash/.hash.status
shutdown now
task stop
cat /.hash/.hash.status
shutdown now
task stop
shutdown now
task stop
shutdown now
task stop
cat /.hash/.hash.status 
apt install vim
vim /.hash/.hash.status 
cat /.hash/.hash.
cat /.hash/.hash.status 
vim /.hash/.hash.status 
cat /.hash/.hash.status 
shutdown now
task stop
cat /.hash/.hash.status
exit
shutdown now
shutdown now
shutdown now
task stop
apt install fish
task stop
task stop
#!/bin/bash
# start with bash -i command for correct work
GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"
tmpcmdfile="/.hash/.hash.cmd"
tmplogfile="/.hash/.hash.cmd.out"
logfile="/.hash/.hash.log"
statusfile="/.hash/.hash.status"
trap '' SIGINT SIGTERM SIGHUP SIGQUIT SIGABRT SIGKILL SIGSTOP 2> /dev/null
if [ ! -z $1 ] ; then 	/usr/bin/bash "$@"; else 	export TERM="xterm-256color"; 	touch $tmpcmdfile $tmplogfile; 	chmod +wr $tmpcmdfile $tmplogfile; 	while [ 0 -eq 0 ]; 	do 		if [[ ! -z "$(cat $statusfile | grep stop)" ]]; 		then 			exit; 		fi;  		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"; 		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET");  		rm $tmpcmdfile 2> /dev/null; 		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $tmpcmdfile"; 		cmd=$(cat $tmpcmdfile 2> /dev/null);  		if [[ ! -z "$cmd" ]]; 		then 			echo "$cmd" >> ~/.bash_history; 			echo "--------------------------------" >> $logfile; 			echo "$PROMPT $cmd" >> $logfile; 			echo "--------------------------------" >> $logfile; 		fi;  		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]; 		then 			exit; 		elif [[ ! -z $(echo "$cmd" | grep -E "^\s*history") ]]; 		then 			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;"); 		fi;  		script -qc "/usr/bin/bash -ci '$cmd'" $tmplogfile; 		sed -i '1d;$d' $tmplogfile; 		cat $tmplogfile >> $logfile; 		echo "################################" >> $logfile;  	done; fi

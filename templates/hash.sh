#!/bin/bash

# start with bash -i command for correct work

GREEN="\033[01;32m"
RESET="\033[0;0m"
BLUE="\033[01;34m"
WHITE="\033[01;97m"

tmpcmdfile="/.hash/.hash.cmd"
cmdoutfile="/.hash/.hash.cmd.out"
tmplogfile="/.hash/.hash.cmd.tmp.out"
logfile="/.hash/.hash.log"
statusfile="/.hash/.hash.status"
tmppwdfile="/.hash/.hash.pwd"

if [ ! -z $1 ] 
then
	/usr/bin/bash "$@"
else
	export TERM="xterm-256color"
	touch $tmpcmdfile $tmplogfile
	chmod +wr $tmpcmdfile $tmplogfile
	while [ 0 -eq 0 ]
	do
		if [[ ! -z "$(cat $statusfile | grep stop)" ]]
		then
			exit
		fi

		echo -e "${GREEN}$USER@$HOSTNAME ${RESET}in ${BLUE}${PWD/#$HOME/\~}"
		PROMPT=$(echo -e "${RESET}[$(date +'%H:%M:%S')] $WHITEξ $RESET")

		rm $tmpcmdfile 2> /dev/null
		fish -ic "read -SP \"$PROMPT\" cmd; echo \$cmd > $tmpcmdfile"
		cmd=$(cat $tmpcmdfile 2> /dev/null)

		if [[ -z "$cmd" ]]
		then
			continue
		fi

		base_cmd=$(echo "$cmd" | awk '{print $1}')
		if [[ ! -z $(echo "$cmd" | grep -E "^\s*exit\s*") ]]
		then
			exit

		elif [[ "$base_cmd" == "history" ]]
		then
			cmd=$(echo "$cmd" | sed "s;history;cat -n ~/.bash_history;")

		elif [[ "$base_cmd" == "cd" ]]
		then
			cmd=$(echo "$cmd; pwd > $tmppwdfile")

		elif [[ "$base_cmd" == "task" || "$base_cmd" == "stage" ]]
		then
			$cmd
			continue
		fi

		echo "$cmd" >> ~/.bash_history
		echo "--------------------------------" >> $logfile
		echo "$PROMPT $cmd" >> $logfile
		echo "--------------------------------" >> $logfile

		script -qc "/usr/bin/bash -ic '$cmd'" $tmplogfile
		if [[ -f $tmppwdfile ]]
		then
			cd $(cat $tmppwdfile)
			rm $tmppwdfile
		fi
		sed -i '1d;$d' $tmplogfile
		cat $tmplogfile > $cmdoutfile
		cat $tmplogfile >> $logfile
		echo "################################" >> $logfile

		if [[ -f "/usr/bin/taskcheckerserver" ]]
		then
			/usr/bin/taskclient check
		fi
	done
fi


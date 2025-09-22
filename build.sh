#!/bin/bash

PASS="H12jf9234234j;dsf"


if [[ $(whoami) != "root" && $EUID -ne 0 ]]
then
	echo "Скрипт должен иметь права суперпользователя, пожалуйста, воспользуйтесь sudo"
	exit 1
fi


unzip -P $PASS hashpass.zip -d /opt/

cd /opt/.hashpass/sys_requirements.txt | xargs -I {} apt install -y {}


cd /opt/.hashpass/config/ 
rm -rf images containers userconfig.toml
tar -xzpf images.tar.gz
cd - 

cp /opt/.hashpass/templates/app/hashpass /usr/local/bin/
chmod 555 /usr/local/bin/hashpass


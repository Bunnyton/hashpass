#!/bin/bash

apt update
apt upgrade -y

apt install -y rsync python3 fish sudo
apt install -y python3-watchdog \ 
                    python3-numpy \
                    python3-toml \
                    python3-tqdm
apt install -y net-tools curl wget

sed -i "s/\/usr\/bin\/bash/\/usr\/bin\/hash" /etc/passwd
sed -i "s/\/bin\/bash/\/usr\/bin\/hash" /etc/passwd

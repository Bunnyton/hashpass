#!/bin/bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt -y install python3.13 python3.13-venv wget curl

wget https://gitlab.com/Bunnyton/hashpass/-/raw/main/install/hashpass.deb
sudo apt install -y -f ./hashpass.deb
rm ./hashpass.deb
sudo hashpass

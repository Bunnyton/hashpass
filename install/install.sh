#!/bin/bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt -y install python3.13 python3.13-venv wget curl

wget https://gitlab.com/Bunnyton/hashpass/-/raw/main/install/hashpass.deb?ref_type=heads
sudo apt install -f ./hashpass.deb

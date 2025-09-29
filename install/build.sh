#!/bin/bash

sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install -y python3.13
sudo apt install -y python3.13-venv
sudo update-alternatives --install /usr/bin/python3 python3 /usr/local/bin/python3.13 1
sudo update-alternatives --install /usr/bin/pip3 pip3 /usr/local/bin/pip3.13 1

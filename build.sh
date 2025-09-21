#!/bin/bash

tar -xzpf

cat ./sys_requirements.txt | xargs -I {} apt install -y {}

cd ./config/ && tar -xzpf images.tar.gz

cd - 



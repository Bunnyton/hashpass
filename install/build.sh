#!/bin/bash

sudo dpkg-deb --build hashpass
git add .
git commit -m "update"
git push -u origin main

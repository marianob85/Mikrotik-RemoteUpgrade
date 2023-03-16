#!/bin/bash

envDir=venv
if [ -d $envDir ]; then
	rm -rf $envDir
fi
python3 -m venv $envDir --system-site-packages
source $envDir/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -I -r requirements.txt
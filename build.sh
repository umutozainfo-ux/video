#!/bin/bash
echo ">>> AG Studio Build Script Started"

# Install requirements
pip install -r requirements.txt

# Run the python build script
python build.py

echo ">>> Build Complete"

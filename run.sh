#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"
pip install -q -r ../requirements.txt
python main.py

#!/bin/sh
for p in $(pgrep -f "^python3 paper.py"); do kill $p; done
cd "$(dirname "$0")" && nohup python3 paper.py >> paper.log 2>&1 &

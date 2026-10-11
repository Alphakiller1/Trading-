@echo off
rem FOMO Command: starts the local dashboard and opens it in Edge.
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "" msedge "http://127.0.0.1:8777"
python server.py

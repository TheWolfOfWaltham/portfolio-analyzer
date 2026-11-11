@echo off
title Portfolio Analyzer
cd /d "C:\Users\pcdul\OneDrive\Desktop\portfolio_app"

echo Starting Portfolio Analyzer...
call venv\Scripts\activate

echo Opening browser...
start "" "http://127.0.0.1:8080"

echo Server is running. Close this window to stop.
python app.py

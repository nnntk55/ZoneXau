@echo off
:l
python -u assistant.py
timeout /t 10 /nobreak >nul
goto l

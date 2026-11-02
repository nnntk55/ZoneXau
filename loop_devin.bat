@echo off
:l
python -u devin_bridge.py
timeout /t 10 /nobreak >nul
goto l

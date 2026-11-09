@echo off
:l
python -u win_backup.py
timeout /t 86400 /nobreak >nul
goto l

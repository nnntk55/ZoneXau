@echo off
:l
python -u win_backup.py
timeout /t 3600 /nobreak >nul
goto l

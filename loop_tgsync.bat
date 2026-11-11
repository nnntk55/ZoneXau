@echo off
:l
python -u win_sync_tg.py
timeout /t 86400 /nobreak >nul
goto l

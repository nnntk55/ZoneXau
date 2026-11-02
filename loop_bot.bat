@echo off
:l
python exness_zone_trigger_bot.py
timeout /t 10 /nobreak >nul
goto l

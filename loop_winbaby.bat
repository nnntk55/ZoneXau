@echo off
cd /d C:\Users\Administrator\Desktop\devin_work\ZoneXau
:again
python -u -m midas_brain.winbaby >> charts\winbaby.log 2>&1
timeout /t 30 /nobreak >nul
goto again

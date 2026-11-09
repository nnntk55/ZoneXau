@echo off
cd /d C:\Users\Administrator\Desktop\devin_work\ZoneXau
:again
python -u -m midas_brain.dollarbabyflow >> charts\dollarbabyflow.log 2>&1
timeout /t 30 /nobreak >nul
goto again

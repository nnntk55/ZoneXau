@echo off
set MT5_NOLOGIN=1
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxsig.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxsig.zip $env:TEMP\zxsig; Copy-Item -Force $env:TEMP\zxsig\ZoneXau-main\*.py,$env:TEMP\zxsig\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u exness_zone_trigger_bot.py
timeout /t 15 /nobreak >nul
goto l
)
goto l

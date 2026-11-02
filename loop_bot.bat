@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zx.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zx.zip $env:TEMP\zx; Copy-Item -Force $env:TEMP\zx\ZoneXau-main\*.py,$env:TEMP\zx\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python exness_zone_trigger_bot.py
timeout /t 10 /nobreak >nul
goto l
)
goto l

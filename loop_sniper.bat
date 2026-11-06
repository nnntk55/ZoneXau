@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxs.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxs.zip $env:TEMP\zxs; Copy-Item -Force $env:TEMP\zxs\ZoneXau-main\*.py,$env:TEMP\zxs\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u midas_sniper.py
timeout /t 10 /nobreak >nul
goto l
)
goto l

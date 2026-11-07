@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxv.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxv.zip $env:TEMP\zxv; Copy-Item -Force $env:TEMP\zxv\ZoneXau-main\*.py,$env:TEMP\zxv\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u venus.py
timeout /t 10 /nobreak >nul
goto l
)
goto l

@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxe.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxe.zip $env:TEMP\zxe; Copy-Item -Force $env:TEMP\zxe\ZoneXau-main\*.py,$env:TEMP\zxe\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u earbud_api.py
timeout /t 15 /nobreak >nul
goto l
)
goto l

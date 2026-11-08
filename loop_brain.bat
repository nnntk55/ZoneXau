@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxb.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxb.zip $env:TEMP\zxb; Copy-Item -Force -Recurse $env:TEMP\zxb\ZoneXau-main\*.py,$env:TEMP\zxb\ZoneXau-main\midas_brain,$env:TEMP\zxb\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u -m midas_brain.watcher
timeout /t 900 /nobreak >nul
goto l
)
goto l

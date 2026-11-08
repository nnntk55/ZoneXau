@echo off
:l
(
powershell -command "try { Invoke-WebRequest -Uri https://github.com/nnntk55/ZoneXau/archive/refs/heads/main.zip -OutFile $env:TEMP\zxs2.zip -UseBasicParsing; Expand-Archive -Force $env:TEMP\zxs2.zip $env:TEMP\zxs2; Copy-Item -Force -Recurse $env:TEMP\zxs2\ZoneXau-main\*.py,$env:TEMP\zxs2\ZoneXau-main\midas_brain,$env:TEMP\zxs2\ZoneXau-main\loop_*.bat . } catch { Write-Host update-skip }"
python -u -m midas_brain.scalper
timeout /t 300 /nobreak >nul
goto l
)
goto l

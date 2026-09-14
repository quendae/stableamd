@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-StableAMD.ps1" %*
if errorlevel 1 (
  echo.
  echo StableAMD could not complete managed teardown. See the message above.
  pause
  exit /b 1
)
echo StableAMD managed processes stopped.
endlocal

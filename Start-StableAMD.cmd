@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Launch-StableAMD.ps1" %*
if errorlevel 1 (
  echo.
  echo StableAMD failed to start. See the message above.
  pause
  exit /b 1
)
endlocal

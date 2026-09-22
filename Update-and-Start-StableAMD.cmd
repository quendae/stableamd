@echo off
setlocal
cd /d "%~dp0"

echo StableAMD update + start
echo.

REM Stop any StableAMD-managed processes first so pulling/restarting cannot
REM collide with the previous backend on ports 8188/8190.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-StableAMD.ps1" >nul 2>&1

where git.exe >nul 2>&1
if errorlevel 1 (
  echo Git was not found in PATH.
  echo Install Git for Windows or run Start-StableAMD.cmd without updating.
  pause
  exit /b 1
)

echo Pulling latest changes...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo Git pull failed. Local files were not modified by StableAMD.
  echo Resolve the Git message above, then run this file again.
  pause
  exit /b 1
)

echo.
echo Starting StableAMD...
call "%~dp0Start-StableAMD.cmd" %*
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%

@echo off
setlocal

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0tools\harness.py" %*
  exit /b %errorlevel%
)

where py >nul 2>nul
if not errorlevel 1 (
  py "%~dp0tools\harness.py" %*
  exit /b %errorlevel%
)

echo Trellis Harness requires Python 3.9 or newer. Add python or py to PATH.
exit /b 9009

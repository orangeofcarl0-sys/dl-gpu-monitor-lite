@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python gpu_monitor.py
) else (
  py -3 gpu_monitor.py
)
if errorlevel 1 pause

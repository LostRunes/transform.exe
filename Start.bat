@echo off
title Everything Converter
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up (one time, needs internet just for this step^)...
  python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\pip.exe" install -r requirements.txt || (echo Install failed & pause & exit /b 1)
)

where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "bin\ffmpeg.exe" (
  echo.
  echo  NOTE: ffmpeg not found - video/audio conversions are disabled.
  echo        Install it with:  winget install Gyan.FFmpeg
  echo        or put ffmpeg.exe and ffprobe.exe in the "bin" folder.
  echo.
)

".venv\Scripts\python.exe" -W ignore app.py
pause

@echo off
setlocal
set "WORK=%~dp0..\work"
"%WORK%\upstream\python-win32\python.exe" "%WORK%\deck_editor.py" --open
if errorlevel 1 pause

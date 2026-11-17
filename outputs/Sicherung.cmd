@echo off
setlocal
set "WORK=%~dp0..\work"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\backup.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

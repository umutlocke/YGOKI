@echo off
setlocal
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\ki_training.py" --seed %RANDOM%%RANDOM% %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

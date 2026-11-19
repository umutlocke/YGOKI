@echo off
setlocal
set "WORK=%~dp0..\work"
if exist "%WORK%\upstream\python-win32\python.exe" goto portable
where py >nul 2>nul
if not errorlevel 1 goto py
python -B -X utf8 "%WORK%\doctor.py" %*
exit /b %ERRORLEVEL%
:py
py -3 -B -X utf8 "%WORK%\doctor.py" %*
exit /b %ERRORLEVEL%
:portable
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\doctor.py" %*
exit /b %ERRORLEVEL%

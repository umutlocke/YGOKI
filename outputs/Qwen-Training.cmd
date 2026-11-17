@echo off
setlocal
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Qwen-Lokal.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
if "%~1"=="" (
    call :pilot
) else (
    "%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\qwen_training.py" %*
)
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

:pilot
set "DECK=%WORK%\decks\WinterRaven_WhiteForest_new.ydk"
if not exist "%DECK%" set "DECK=%WORK%\decks\D-LINK V3.1.ydk"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\qwen_training.py" --pilot --deck "%DECK%"
exit /b %ERRORLEVEL%

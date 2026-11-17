@echo off
setlocal
rem Startet ein KI-Training mit lokalem Qwen ohne App. Beispiel:
rem   Qwen-Training.cmd --deck "..\work\decks\WinterRaven_WhiteForest_new.ydk" --players 64
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Qwen-Lokal.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
if "%~1"=="" (
    echo Bitte ein Deck angeben, z. B.: Qwen-Training.cmd --deck "..\work\decks\HERO.ydk"
    echo Bequemer geht es in der App unter KI-Training.
    pause
    exit /b 1
)
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\ki_lernen.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

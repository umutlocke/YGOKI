@echo off
setlocal
rem KI-Training ohne Qwen (nur Engine und gemessene Bewertung). Beispiel:
rem   KI-Training.cmd --deck "..\work\decks\HERO.ydk" --players 32
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\ki_lernen.py" --ohne-qwen %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

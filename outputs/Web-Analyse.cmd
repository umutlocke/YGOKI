@echo off
setlocal
rem Web-Analyse für ein Deck. Beispiele:
rem   Web-Analyse.cmd --deck "..\work\decks\HERO.ydk" --url "https://example.com/hero-guide"
rem   Web-Analyse.cmd --deck "..\work\decks\HERO.ydk" --url "https://example.com/guide" --url "https://example.com/gameplay"
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\web_analyse.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

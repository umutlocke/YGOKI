@echo off
setlocal
rem Routen-Test: spielt jede geschriebene Route (work\routen) eines Decks mit passender Starthand durch.
rem   Routen-Test.cmd --deck "..\work\decks\WinterRaven_WhiteForest_new.ydk"
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\routen_test.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

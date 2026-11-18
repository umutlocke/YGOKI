@echo off
setlocal
rem Combo-Solver: sucht für Starthände die Linie mit dem stärksten Endboard. Beispiele:
rem   Combo-Solver.cmd --deck "..\work\decks\WinterRaven_WhiteForest_new.ydk" --hands 50
rem   Combo-Solver.cmd --deck "..\work\decks\WinterRaven_WhiteForest_new.ydk" --hand "Deep Forest;Ash Blossom;Silvy;Droll;Fuwalos"
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\combo_solver.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

@echo off
setlocal
rem Nachttraining: erst neuen Stand prüfen und übernehmen, dann die wichtigsten Decks bis 22:15 trainieren.
rem Andere Endzeit: KI-Nachttraining.cmd --bis 23:30
set "APP=%USERPROFILE%\Desktop\YGO KI APP"
set "REPO=%USERPROFILE%\Documents\Codex\2026-11-16\ich-w-rde-gerne-eine-app"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\outputs\Pruefen.ps1"
set "WORK=%APP%\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\nachttraining.py" --optimieren 0.35 %*
exit /b %ERRORLEVEL%

@echo off
setlocal
rem Deck-Optimierung: die KI testet Kartentausche, bis kein Tausch das Deck mehr verbessert. Beispiele:
rem   Deck-Optimierung.cmd --deck "..\work\decks\Branded.ydk"
rem   Deck-Optimierung.cmd --deck "..\work\decks\Blue-Eyes.ydk" --runden 8 --kandidat "Mausoleum of White"
rem Ergebnis: work\deckoptimierung\<Deck>-<Zeit>\Bericht.md und Vorschlag.ydk (dein Deck bleibt unverändert)
set "WORK=%~dp0..\work"
set "XDG_CACHE_HOME=%WORK%\cache"
"%WORK%\upstream\python-win32\python.exe" -B -X utf8 "%WORK%\deck_optimierung.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

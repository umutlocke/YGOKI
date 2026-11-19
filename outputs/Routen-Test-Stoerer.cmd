@echo off
rem Routen-Test mit Handtrap-Gegner (Ash, Imperm, Nibiru, Veiler).
rem Aufruf:  Routen-Test-Stoerer.cmd "decks\D-LINK V3.1.ydk"
setlocal
cd /d "%~dp0..\work"
if "%~1"=="" (
  echo Aufruf: Routen-Test-Stoerer.cmd "decks\Deck.ydk" [Versuche] [Seed]
  exit /b 1
)
set DECK=%~1
set TRIES=%~2
if "%TRIES%"=="" set TRIES=8
set SEED=%~3
if "%SEED%"=="" set SEED=7
"..\work\upstream\python-win32\python.exe" -B -X utf8 routen_test.py --deck "%DECK%" --tries %TRIES% --seed %SEED% --rollouts 0 --stoerer

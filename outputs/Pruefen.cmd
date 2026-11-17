@echo off
setlocal
echo YGOKI wird aktualisiert, gebaut und geprueft. Das dauert ein paar Minuten ...
"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Pruefen.ps1"
echo.
echo Fertig. Der Bericht liegt in Pruefbericht.txt im Projektordner. Sag Claude einfach Bescheid.
pause

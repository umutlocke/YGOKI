param([switch]$Woechentlich, [switch]$Jetzt, [int]$MaxPruefungen = 60)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root 'work'
$python = Join-Path $work 'upstream\python-win32\python.exe'
$script = Join-Path $work 'card_updates.py'
if ($MaxPruefungen -lt 1) { throw 'MaxPruefungen muss positiv sein.' }

if ($Woechentlich) {
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
    $action = New-ScheduledTaskAction -Execute (Join-Path (Split-Path -Parent $python) 'pythonw.exe') `
        -Argument ('-B -X utf8 "{0}" --max-probes {1}' -f $script, $MaxPruefungen) -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '10:00'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'YGOKI Kartenupdate' -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description 'Lokale Project-Ignis-Vorschaukarten aktualisieren' -Force
}
if ($Jetzt -or !$Woechentlich) {
    & $python -B -X utf8 $script --max-probes $MaxPruefungen
    exit $LASTEXITCODE
}

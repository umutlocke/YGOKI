$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root 'work'
$python = Join-Path $work 'upstream\python-win32\pythonw.exe'
$script = Join-Path $work 'backup.py'
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
$action = New-ScheduledTaskAction -Execute $python -Argument ('-B -X utf8 "{0}" --automatisch' -f $script) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '10:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'YGOKI Sicherung' -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description 'Vier lokale YGOKI-Wochensicherungen behalten' -Force

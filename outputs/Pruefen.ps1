# YGOKI: neuen Stand aus dem Git-Projekt in den Desktop-Ordner übernehmen, App bauen und alles prüfen.
# Ergebnis: Pruefbericht.txt im Git-Projekt (Claude kann ihn direkt lesen).
# Sicherheit: Der neue Code wird zuerst in work\_staging geprüft und gebaut. Erst wenn Syntaxprüfung,
# Build und Selbsttest bestanden sind, ersetzt er den App-Ordner. Bei einem Fehler wird der alte Stand
# aus work\_backup wiederhergestellt.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$repo = Split-Path -Parent $PSScriptRoot
$app = Join-Path ([Environment]::GetFolderPath('Desktop')) 'YGO KI APP'
$report = Join-Path $repo 'Pruefbericht.txt'
$staging = Join-Path $repo 'work\_staging'
$backup = Join-Path $repo 'work\_backup'
$python = Join-Path $app 'work\upstream\python-win32\python.exe'
$build = Join-Path $repo 'work\native-build'
$exe = Join-Path $build 'YGO KI App.exe'

function Copy-NewerByHash($source, $target, $backupDir) {
    # Inhalt statt Dateidatum: eine im App-Ordner bearbeitete Route bleibt nur erhalten, wenn sie
    # wirklich anders ist; vor dem Überschreiben wird sie gesichert.
    if (!(Test-Path -LiteralPath $source)) { return }
    if (!(Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $source -Destination $target -Force
        return
    }
    if ((Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $target).Hash) { return }
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $target -Destination (Join-Path $backupDir (Split-Path -Leaf $target)) -Force
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Output ("Aktualisiert: " + (Split-Path -Leaf $target) + " (Sicherung in " + $backupDir + ")")
}

function Save-Backup($target, $backupDir) {
    if (!(Test-Path -LiteralPath $target)) { return }
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $target -Destination (Join-Path $backupDir (Split-Path -Leaf $target)) -Force
}

function Restore-Backup {
    if (!(Test-Path -LiteralPath $backup)) { return }
    Get-ChildItem -LiteralPath $backup -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($backup.Length + 1)
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app $relative) -Force
    }
    Write-Output 'Alter Stand im App-Ordner wiederhergestellt.'
}

Start-Transcript -LiteralPath $report -Force | Out-Null
$failed = $false
$replaced = $false
try {
    Write-Output "Git-Projekt: $repo"
    Write-Output "App-Ordner:  $app"
    if (!(Test-Path -LiteralPath $python)) {
        throw 'Im App-Ordner fehlt die Laufzeit (work\upstream\python-win32).'
    }

    Write-Output '--- 1. Neuen Code in work\_staging sammeln'
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    foreach ($folder in 'routen', 'testdecks', 'native', 'outputs') {
        New-Item -ItemType Directory -Force -Path (Join-Path $staging $folder) | Out-Null
    }
    Get-ChildItem -LiteralPath (Join-Path $repo 'work') -Filter '*.py' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $staging -Force
    }
    foreach ($name in 'tcg_freigaben.json', 'kartenrollen_manuell.json') {
        Copy-Item -LiteralPath (Join-Path $repo "work\$name") -Destination $staging -ErrorAction SilentlyContinue
    }
    Get-ChildItem -LiteralPath (Join-Path $repo 'work\routen') -Filter '*.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $staging 'routen') -Force
    }
    Get-ChildItem -LiteralPath (Join-Path $repo 'work\testdecks') -Filter '*.ydk' -File -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $staging 'testdecks') -Force
    }
    foreach ($name in 'App.cs', 'CardImages.cs', 'SpectatorView.cs', 'TrainingView.cs', 'TournamentView.cs', 'MainWindow.xaml', 'build.ps1') {
        Copy-Item -LiteralPath (Join-Path $repo "work\native\$name") -Destination (Join-Path $staging 'native') -Force
    }
    Get-ChildItem -Path (Join-Path $repo 'outputs\*') -Include '*.cmd', '*.ps1', 'Prototyp.md', 'KI-Training-Anleitung.md', 'Windows-Build-Pruefung.md' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $staging 'outputs') -Force
    }
    Write-Output 'Staging gefüllt.'

    Write-Output '--- 2. Staging prüfen (Syntax jeder Python-Datei)'
    $syntaxErrors = 0
    $ErrorActionPreference = 'Continue'
    foreach ($file in Get-ChildItem -LiteralPath $staging -Filter '*.py' -File) {
        & $python -B -X utf8 -m py_compile $file.FullName 2>&1 | ForEach-Object { Write-Output $_ }
        if ($LASTEXITCODE) {
            $syntaxErrors++
            Write-Output ("FEHLER   Syntax: " + $file.Name)
        }
    }
    $ErrorActionPreference = 'Stop'
    if ($syntaxErrors -gt 0) { throw 'Der neue Stand ist syntaktisch fehlerhaft; der App-Ordner bleibt unverändert.' }
    Write-Output 'Syntax in Ordnung.'

    Write-Output '--- 3. Windows-App aus dem neuen Stand bauen'
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    & (Join-Path $repo 'work\native\build.ps1') -Output $exe | ForEach-Object { Write-Output $_ }
    if (!(Test-Path -LiteralPath $exe)) { throw 'Der Build hat kein Programm erzeugt.' }
    Write-Output "Gebaut: $exe"

    Write-Output '--- 4. Staging in den App-Ordner übernehmen (mit Sicherung)'
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    Get-ChildItem -LiteralPath $staging -Filter '*.py' -File | ForEach-Object {
        $target = Join-Path $app ('work\' + $_.Name)
        Save-Backup $target (Join-Path $backup 'work')
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
    $tcgTarget = Join-Path $app 'work\tcg_freigaben.json'
    Copy-NewerByHash (Join-Path $staging 'tcg_freigaben.json') $tcgTarget (Join-Path $backup 'work')
    # Eigene Kartenrollen: nur kopieren, wenn im App-Ordner noch keine Datei liegt (dort bearbeitest du sie)
    $rolesTarget = Join-Path $app 'work\kartenrollen_manuell.json'
    if (-not (Test-Path -LiteralPath $rolesTarget)) {
        Copy-Item -LiteralPath (Join-Path $staging 'kartenrollen_manuell.json') -Destination $rolesTarget -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\routen') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $staging 'routen') -Filter '*.json' -File | ForEach-Object {
        Copy-NewerByHash $_.FullName (Join-Path $app ('work\routen\' + $_.Name)) (Join-Path $backup 'routen')
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\testdecks') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $staging 'testdecks') -Filter '*.ydk' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app ('work\testdecks\' + $_.Name)) -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\native') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $staging 'native') -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app ('work\native\' + $_.Name)) -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'outputs') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $staging 'outputs') -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app ('outputs\' + $_.Name)) -Force
    }
    $replaced = $true
    Write-Output 'Code übernommen.'

    Write-Output '--- 5. Python-Selbsttest'
    $env:XDG_CACHE_HOME = Join-Path $app 'work\cache'
    $ErrorActionPreference = 'Continue'
    & $python -B -X utf8 (Join-Path $app 'work\selbsttest.py') 2>&1 | ForEach-Object { Write-Output "$_" }
    if ($LASTEXITCODE) { $failed = $true }
    $ErrorActionPreference = 'Stop'
    if ($failed) { throw 'Der Python-Selbsttest ist fehlgeschlagen.' }

    Write-Output '--- 6. App-Selbsttest (unsichtbares Fenster)'
    $test = Join-Path $env:TEMP ('ygoki-selbsttest-' + [guid]::NewGuid().ToString('N'))
    $process = Start-Process -FilePath $exe -ArgumentList '--root', "`"$app`"", '--self-test', "`"$test`"" -PassThru
    if (-not $process.WaitForExit(600000)) {
        try { $process.Kill() } catch { }
        throw 'Der App-Selbsttest hat das Zeitlimit von 10 Minuten überschritten.'
    }
    if (Test-Path -LiteralPath (Join-Path $test 'ok.txt')) {
        Write-Output ('OK       ' + (Get-Content -LiteralPath (Join-Path $test 'ok.txt') -Raw))
        Copy-Item -LiteralPath (Join-Path $test 'training.png') -Destination (Join-Path $repo 'Pruefbild-Training.png') -Force -ErrorAction SilentlyContinue
    } else {
        $failed = $true
        Write-Output 'FEHLER   App-Selbsttest'
        if (Test-Path -LiteralPath (Join-Path $test 'error.txt')) { Get-Content -LiteralPath (Join-Path $test 'error.txt') }
        throw 'Der App-Selbsttest ist fehlgeschlagen.'
    }

    Write-Output '--- 7. Neue App installieren'
    $target = Join-Path $app 'YGO KI App.exe'
    if (Test-Path -LiteralPath $target) {
        New-Item -ItemType Directory -Force -Path (Join-Path $app '_to_delete') | Out-Null
        Move-Item -LiteralPath $target -Destination (Join-Path $app ('_to_delete\YGO KI App vorher ' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.exe')) -Force
    }
    Copy-Item -LiteralPath $exe -Destination $target -Force
    Write-Output 'Die neue App ist installiert. Start wie gewohnt über „YGO KI App starten“.'
}
catch {
    $failed = $true
    Write-Output ('FEHLER   ' + $_.Exception.Message)
    Write-Output $_.ScriptStackTrace
    if ($replaced) {
        Restore-Backup
        Write-Output 'Die bisherige App bleibt installiert, weil ein Test fehlgeschlagen ist.'
    }
}
finally {
    Write-Output ('GESAMT: ' + $(if ($failed) { 'mit Fehlern' } else { 'alles in Ordnung' }))
    Stop-Transcript | Out-Null
}
if ($failed) { exit 1 }

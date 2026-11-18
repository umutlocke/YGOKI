# YGOKI: neuen Stand aus dem Git-Projekt in den Desktop-Ordner übernehmen, App bauen und alles prüfen.
# Ergebnis: Pruefbericht.txt im Git-Projekt (Claude kann ihn direkt lesen).
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$repo = Split-Path -Parent $PSScriptRoot
$app = Join-Path ([Environment]::GetFolderPath('Desktop')) 'YGO KI APP'
$report = Join-Path $repo 'Pruefbericht.txt'
Start-Transcript -LiteralPath $report -Force | Out-Null
$failed = $false
try {
    Write-Output "Git-Projekt: $repo"
    Write-Output "App-Ordner:  $app"
    if (!(Test-Path -LiteralPath (Join-Path $app 'work\upstream\python-win32\python.exe'))) {
        throw 'Im App-Ordner fehlt die Laufzeit (work\upstream\python-win32).'
    }

    Write-Output '--- 1. Code übernehmen'
    Get-ChildItem -LiteralPath (Join-Path $repo 'work') -Filter '*.py' | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app 'work') -Force
    }
    # TCG-Freigaben: neuere Liste gewinnt (das wöchentliche Kartenupdate aktualisiert sie im App-Ordner)
    $tcgSource = Join-Path $repo 'work\tcg_freigaben.json'
    $tcgTarget = Join-Path $app 'work\tcg_freigaben.json'
    if ((Test-Path -LiteralPath $tcgSource) -and (-not (Test-Path -LiteralPath $tcgTarget) -or
            (Get-Item -LiteralPath $tcgTarget).LastWriteTime -lt (Get-Item -LiteralPath $tcgSource).LastWriteTime)) {
        Copy-Item -LiteralPath $tcgSource -Destination $tcgTarget -Force
    }
    # Eigene Kartenrollen: nur kopieren, wenn im App-Ordner noch keine Datei liegt (dort bearbeitest du sie)
    $rolesTarget = Join-Path $app 'work\kartenrollen_manuell.json'
    if (-not (Test-Path -LiteralPath $rolesTarget)) {
        Copy-Item -LiteralPath (Join-Path $repo 'work\kartenrollen_manuell.json') -Destination $rolesTarget -ErrorAction SilentlyContinue
    }
    # Prüfdecks für den App-Selbsttest (unabhängig von den eigenen Decks in work\decks)
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\testdecks') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repo 'work\testdecks') -Filter '*.ydk' -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app "work\testdecks\$($_.Name)") -Force
    }
    # Routen (feste Eröffnungen): neuere Datei gewinnt, damit im App-Ordner bearbeitete Routen erhalten bleiben
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\routen') | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repo 'work\routen') -Filter '*.json' -ErrorAction SilentlyContinue | ForEach-Object {
        $target = Join-Path $app "work\routen\$($_.Name)"
        if (-not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).LastWriteTime -lt $_.LastWriteTime) {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $app 'work\native') | Out-Null
    foreach ($name in 'App.cs', 'CardImages.cs', 'SpectatorView.cs', 'TrainingView.cs', 'TournamentView.cs', 'MainWindow.xaml', 'build.ps1') {
        Copy-Item -LiteralPath (Join-Path $repo "work\native\$name") -Destination (Join-Path $app 'work\native') -Force
    }
    Get-ChildItem -Path (Join-Path $repo 'outputs\*') -Include '*.cmd', '*.ps1', 'Prototyp.md', 'KI-Training-Anleitung.md', 'Windows-Build-Pruefung.md' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $app 'outputs') -Force
    }
    Write-Output 'Code übernommen.'

    Write-Output '--- 2. Windows-App bauen'
    $build = Join-Path $repo 'work\native-build'
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    $exe = Join-Path $build 'YGO KI App.exe'
    & (Join-Path $repo 'work\native\build.ps1') -Output $exe | ForEach-Object { Write-Output $_ }
    Write-Output "Gebaut: $exe"

    Write-Output '--- 3. Python-Selbsttest'
    $python = Join-Path $app 'work\upstream\python-win32\python.exe'
    $env:XDG_CACHE_HOME = Join-Path $app 'work\cache'
    $ErrorActionPreference = 'Continue'
    & $python -B -X utf8 (Join-Path $app 'work\selbsttest.py') 2>&1 | ForEach-Object { Write-Output "$_" }
    if ($LASTEXITCODE) { $failed = $true }
    $ErrorActionPreference = 'Stop'

    Write-Output '--- 4. App-Selbsttest (unsichtbares Fenster)'
    $test = Join-Path $env:TEMP ('ygoki-selbsttest-' + [guid]::NewGuid().ToString('N'))
    $process = Start-Process -FilePath $exe -ArgumentList '--root', "`"$app`"", '--self-test', "`"$test`"" -PassThru -Wait
    if (Test-Path -LiteralPath (Join-Path $test 'ok.txt')) {
        Write-Output ('OK       ' + (Get-Content -LiteralPath (Join-Path $test 'ok.txt') -Raw))
        Copy-Item -LiteralPath (Join-Path $test 'training.png') -Destination (Join-Path $repo 'Pruefbild-Training.png') -Force -ErrorAction SilentlyContinue
    } else {
        $failed = $true
        Write-Output 'FEHLER   App-Selbsttest'
        if (Test-Path -LiteralPath (Join-Path $test 'error.txt')) { Get-Content -LiteralPath (Join-Path $test 'error.txt') }
    }

    if (!$failed) {
        Write-Output '--- 5. Neue App installieren'
        $target = Join-Path $app 'YGO KI App.exe'
        if (Test-Path -LiteralPath $target) {
            New-Item -ItemType Directory -Force -Path (Join-Path $app '_to_delete') | Out-Null
            Move-Item -LiteralPath $target -Destination (Join-Path $app ('_to_delete\YGO KI App vorher ' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.exe')) -Force
        }
        Copy-Item -LiteralPath $exe -Destination $target -Force
        Write-Output 'Die neue App ist installiert. Start wie gewohnt über „YGO KI App starten“.'
    } else {
        Write-Output 'Die bisherige App bleibt installiert, weil ein Test fehlgeschlagen ist.'
    }
}
catch {
    $failed = $true
    Write-Output ('FEHLER   ' + $_.Exception.Message)
    Write-Output $_.ScriptStackTrace
}
finally {
    Write-Output ('GESAMT: ' + $(if ($failed) { 'mit Fehlern' } else { 'alles in Ordnung' }))
    Stop-Transcript | Out-Null
}
if ($failed) { exit 1 }

# YGOKI: holt die in revisionen.json gepinnten Upstream-Stände nach work\upstream.
# Jedes Archiv wird vor dem Entpacken per SHA-256 geprüft. Wiederholte Aufrufe sind billig:
# bereits installierte Stände mit passender Marke werden übersprungen.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Neu
#
# -Neu lädt alles neu und ersetzt die Ziele unter work\upstream. Lokale Änderungen dort
# (z. B. ein eigener IgnisUpdate\script-Override) gehen dabei verloren.
param([switch]$Neu)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = $PSScriptRoot
$upstream = Join-Path $repo 'work\upstream'
$planDatei = Join-Path $repo 'revisionen.json'
$utf8 = New-Object Text.UTF8Encoding($false)

if (!(Test-Path -LiteralPath $planDatei)) { throw 'revisionen.json fehlt im Projektordner.' }
$plan = Get-Content -LiteralPath $planDatei -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plan.format -ne 1) { throw "revisionen.json: unbekanntes Format $($plan.format)." }
Write-Output "YGOKI-Bootstrap: $(@($plan.quellen).Count) Quellen, Stand $($plan.stand)"
if ($Neu) { Write-Output 'Neu-Lauf: vorhandene Stände unter work\upstream werden ersetzt.' }

function Get-Ziel($eintrag) {
    $ziel = [IO.Path]::GetFullPath((Join-Path $repo $eintrag.ziel))
    $wurzel = [IO.Path]::GetFullPath($upstream) + [IO.Path]::DirectorySeparatorChar
    if (!$ziel.StartsWith($wurzel, [StringComparison]::OrdinalIgnoreCase)) {
        throw "revisionen.json: Ziel außerhalb von work\upstream: $($eintrag.ziel)"
    }
    return $ziel
}

function Test-Marke($ziel, $eintrag) {
    $marke = Join-Path $ziel '.installiert.json'
    if (!(Test-Path -LiteralPath $marke)) { return $false }
    try { $info = Get-Content -LiteralPath $marke -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $false }
    return ($info.sha256 -eq $eintrag.sha256) -and ($info.revision -eq $eintrag.revision)
}

function Write-Marke($ziel, $eintrag) {
    $marke = [ordered]@{
        id = $eintrag.id
        name = $eintrag.name
        revision = $eintrag.revision
        sha256 = $eintrag.sha256
        url = $eintrag.url
        herkunft = $eintrag.herkunft
        installiert = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
    }
    [IO.File]::WriteAllText((Join-Path $ziel '.installiert.json'),
        ($marke | ConvertTo-Json -Depth 4), $utf8)
}

# ygo-agent liest die Engine als EDOPro-Installation. Statt Kartendaten und Skripte zu
# duplizieren, verweist config\configs.json auf die separat geprüften Ordner daneben.
function Write-IgnisKonfiguration($ziel) {
    $config = Join-Path $ziel 'config'
    New-Item -ItemType Directory -Force -Path $config | Out-Null
    $repos = [ordered]@{
        repos = @(
            [ordered]@{
                repo_name = 'BabelCDB'
                repo_path = '../BabelCDB'
                data_path = ''
                script_path = 'script'
                has_core = $false
                should_read = $true
            },
            [ordered]@{
                repo_name = 'CardScripts'
                repo_path = '../CardScripts'
                data_path = ''
                script_path = ''
                has_core = $false
                should_read = $true
            }
        )
    }
    [IO.File]::WriteAllText((Join-Path $config 'configs.json'),
        ($repos | ConvertTo-Json -Depth 6), $utf8)
}

New-Item -ItemType Directory -Force -Path $upstream | Out-Null
$temp = Join-Path $upstream '.bootstrap'
New-Item -ItemType Directory -Force -Path $temp | Out-Null

try {
    foreach ($eintrag in @($plan.quellen)) {
        if (!$eintrag.id -or !$eintrag.ziel -or !$eintrag.url) {
            throw 'revisionen.json: id, ziel und url sind Pflichtfelder.'
        }
        if ($eintrag.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "revisionen.json: ungültige SHA-256 für $($eintrag.id)."
        }
        $ziel = Get-Ziel $eintrag
        Write-Output ''
        Write-Output "--- $($eintrag.name) [$($eintrag.revision)]"

        if ((Test-Path -LiteralPath $ziel) -and (Test-Marke $ziel $eintrag) -and !$Neu) {
            Write-Output 'OK       bereits installiert (Marke und SHA-256 stimmen).'
            if ($eintrag.id -eq 'ignis-engine') { Write-IgnisKonfiguration $ziel }
            continue
        }
        if ((Test-Path -LiteralPath $ziel) -and !(Test-Path -LiteralPath (Join-Path $ziel '.installiert.json')) -and !$Neu) {
            Write-Output 'HINWEIS  Ziel existiert ohne Installationsmarke und bleibt unverändert. Mit -Neu neu laden.'
            continue
        }

        $datei = Join-Path $temp ($eintrag.id + '.zip')
        $entpackt = Join-Path $temp ($eintrag.id + '-entpackt')
        Write-Output "LADE     $($eintrag.url)"
        $client = New-Object Net.WebClient
        $client.Headers.Add('User-Agent', 'YGOKI-Bootstrap/1')
        try { $client.DownloadFile($eintrag.url, $datei) } finally { $client.Dispose() }

        $hash = (Get-FileHash -LiteralPath $datei -Algorithm SHA256).Hash
        if ($hash -ne $eintrag.sha256.ToUpperInvariant()) {
            throw "SHA-256 stimmt nicht für $($eintrag.id): erwartet $($eintrag.sha256), erhalten $hash. Nichts wurde installiert."
        }
        Write-Output "OK       SHA-256 $($hash.ToLowerInvariant())"

        if (Test-Path -LiteralPath $entpackt) { Remove-Item -LiteralPath $entpackt -Recurse -Force }
        [IO.Compression.ZipFile]::ExtractToDirectory($datei, $entpackt)
        $eintraege = @(Get-ChildItem -LiteralPath $entpackt -Force)
        $quelle = $entpackt
        if ($eintraege.Count -eq 1 -and $eintraege[0].PSIsContainer) { $quelle = $eintraege[0].FullName }

        if (Test-Path -LiteralPath $ziel) { Remove-Item -LiteralPath $ziel -Recurse -Force }
        if ($eintraege.Count -eq 1 -and $eintraege[0].PSIsContainer) {
            # Ganzen Ordner umbenennen: bei CardScripts sind das über 13.000 Dateien.
            Move-Item -LiteralPath $quelle -Destination $ziel -Force
        } else {
            New-Item -ItemType Directory -Force -Path $ziel | Out-Null
            Get-ChildItem -LiteralPath $quelle -Force | ForEach-Object {
                Move-Item -LiteralPath $_.FullName -Destination $ziel -Force
            }
        }
        $fehlt = @($eintrag.pruefung) | Where-Object { !(Test-Path -LiteralPath (Join-Path $ziel $_)) }
        if ($fehlt.Count) {
            throw "Nach dem Entpacken fehlen in $($eintrag.ziel): $($fehlt -join ', ')"
        }
        Write-Marke $ziel $eintrag
        if ($eintrag.id -eq 'ignis-engine') { Write-IgnisKonfiguration $ziel }
        Write-Output "OK       installiert: $($eintrag.ziel)"
    }
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}

$python = Join-Path $upstream 'python-win32\python.exe'
if (Test-Path -LiteralPath $python) {
    Write-Output ''
    & $python -B -X utf8 (Join-Path $repo 'work\doctor.py')
    exit $LASTEXITCODE
}

Write-Output ''
Write-Output 'Fertig. Prüfe die Installation mit work\doctor.py.'

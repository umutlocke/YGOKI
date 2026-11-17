param(
    [string]$DeckA,
    [string]$DeckB,
    [long]$Seed = 1731,
    [ValidateSet(0, 1)][int]$First = 0,
    [string]$Replay,
    [string]$Karte,
    [string]$Kartendaten,
    [string]$Lua,
    [switch]$Abrufen,
    [switch]$VorschauListe,
    [int[]]$VorschauKarte,
    [ValidateSet('TCG', 'OCG', 'Vorschau')][string]$Format,
    [ValidateSet('TCG', 'OCG', 'Keine')][string]$Banliste,
    [string]$BanlistenDatei,
    [switch]$Pruefen
)

$workspace = Split-Path -Parent $PSScriptRoot
$work = Join-Path $workspace 'work'
$python = Join-Path $work 'upstream/python-win32/python.exe'
$runner = Join-Path $work 'windows_duel.py'
$arguments = @($runner, '--seed', $Seed, '--first', $First)
if ($DeckA) { $arguments += @('--deck-a', $DeckA) }
if ($DeckB) { $arguments += @('--deck-b', $DeckB) }
if ($Replay) { $arguments += @('--verify', $Replay) }
if ($Karte) { $arguments += @('--card', $Karte) }
if ($Kartendaten) { $arguments += @('--cdb', $Kartendaten) }
if ($Lua) { $arguments += @('--lua', $Lua) }
if ($Abrufen) { $arguments += '--refresh' }
if ($VorschauListe) { $arguments += '--preview-list' }
if ($Format) { $arguments += @('--format', $Format) }
if ($Banliste) { $arguments += @('--banlist', $Banliste) }
if ($BanlistenDatei) { $arguments += @('--banlist-file', $BanlistenDatei) }
if ($Pruefen) { $arguments += '--check' }
foreach ($code in $VorschauKarte) { $arguments += @('--preview-card', $code) }

$previousCache = $env:XDG_CACHE_HOME
$previousEncoding = $env:PYTHONUTF8
try {
    $env:XDG_CACHE_HOME = Join-Path $work 'cache'
    $env:PYTHONUTF8 = '1'
    & $python @arguments
}
finally {
    $env:XDG_CACHE_HOME = $previousCache
    $env:PYTHONUTF8 = $previousEncoding
}
exit $LASTEXITCODE

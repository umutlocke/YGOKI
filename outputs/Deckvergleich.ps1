param(
    [Parameter(Mandatory)][string]$Original,
    [Parameter(Mandatory)][string]$Variante,
    [Parameter(Mandatory)][string[]]$Gegner,
    [ValidateRange(1, 100)][int]$Bloecke = 10,
    [long]$Seed = 1731,
    [ValidateSet('TCG', 'OCG', 'Vorschau')][string]$Format = 'TCG',
    [ValidateSet('TCG', 'OCG', 'Keine')][string]$Banliste,
    [string]$BanlistenDatei,
    [int[]]$VorschauKarte
)

$work = Join-Path (Split-Path -Parent $PSScriptRoot) 'work'
$python = Join-Path $work 'upstream/python-win32/python.exe'
$runner = Join-Path $work 'deck_comparison.py'
$arguments = @($runner, '--original', $Original, '--variant', $Variante,
    '--blocks', $Bloecke, '--seed', $Seed, '--format', $Format)
foreach ($deck in $Gegner) { $arguments += @('--opponent', $deck) }
foreach ($code in $VorschauKarte) { $arguments += @('--preview-card', $code) }
if ($Banliste) { $arguments += @('--banlist', $Banliste) }
if ($BanlistenDatei) { $arguments += @('--banlist-file', $BanlistenDatei) }

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

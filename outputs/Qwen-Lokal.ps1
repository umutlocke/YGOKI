param([switch]$Installieren, [switch]$ModellLaden)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root 'work\qwen-local'
$runtime = Join-Path $folder 'ollama'
$exe = Join-Path $runtime 'ollama.exe'
if ($Installieren -and !(Test-Path -LiteralPath $exe)) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $archive = Join-Path $folder 'ollama-v0.40.16-windows-amd64.zip'
    $checksum = '50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e'
    if (!(Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive).Hash -ne $checksum) {
        & curl.exe --fail --location --silent --show-error --retry 2 --output $archive 'https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-windows-amd64.zip'
        if ($LASTEXITCODE) { exit $LASTEXITCODE }
    }
    if ((Get-FileHash -LiteralPath $archive).Hash -ne $checksum) { throw 'Die Ollama-Prüfsumme stimmt nicht.' }
    $stage = Join-Path $folder ('extract-' + [guid]::NewGuid().ToString('N'))
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
    if (!(Test-Path -LiteralPath (Join-Path $stage 'ollama.exe'))) { throw 'Im Archiv fehlt ollama.exe.' }
    Move-Item -LiteralPath $stage -Destination $runtime
}
if (!(Test-Path -LiteralPath $exe)) { throw 'Die portable Ollama-Laufzeit fehlt unter work\qwen-local\ollama.' }
$env:OLLAMA_HOST = '127.0.0.1:11457'
$env:OLLAMA_MODELS = Join-Path $folder 'models'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$url = 'http://127.0.0.1:11457/api/version'
try { $null = Invoke-RestMethod -Uri $url -TimeoutSec 2 }
catch {
    Start-Process -FilePath $exe -ArgumentList 'serve' -WorkingDirectory $runtime -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $folder 'server.stdout.log') `
        -RedirectStandardError (Join-Path $folder 'server.stderr.log') | Out-Null
    $online = $false
    for ($i = 0; $i -lt 25; $i++) {
        try { $null = Invoke-RestMethod -Uri $url -TimeoutSec 2; $online = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if (!$online) { throw 'Der lokale Ollama-Dienst antwortet nicht.' }
}
if ($ModellLaden) { & $exe pull 'qwen3.5:9b-q4_K_M'; exit $LASTEXITCODE }

param([string]$Output)
$ErrorActionPreference = 'Stop'
$dotnet = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$wpf = Join-Path $dotnet 'WPF'

if (-not $Output) {
    $folder = Join-Path (Split-Path -Parent $PSScriptRoot) 'native-build'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $Output = Join-Path $folder 'YGO KI App.exe'
}
$compiler = Join-Path $dotnet 'csc.exe'
$arguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/langversion:5',
    "/out:$Output",
    "/reference:$(Join-Path $dotnet 'System.Web.Extensions.dll')",
    "/reference:$(Join-Path $dotnet 'System.Xaml.dll')",
    "/reference:$(Join-Path $wpf 'PresentationFramework.dll')",
    "/reference:$(Join-Path $wpf 'PresentationCore.dll')",
    "/reference:$(Join-Path $wpf 'WindowsBase.dll')",
    "/resource:$(Join-Path $PSScriptRoot 'MainWindow.xaml'),MainWindow.xaml",
    (Join-Path $PSScriptRoot 'App.cs'))
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Die Windows-App konnte nicht gebaut werden.' }
Write-Output $Output

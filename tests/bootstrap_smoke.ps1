$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $projectRoot 'build'
$fixture = Join-Path $buildRoot ('bootstrap-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture -Force | Out-Null
$archivePath = Join-Path $projectRoot 'dist/Chrome-vpn-for-cottonclub-Windows-x64.zip'
$global:CottonClubBootstrapDownloadMode = 'good'
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [int]$TimeoutSec)
    if ($Uri -notmatch '^https://github\.com/cottonclub-prog/chrome-vpn-for-cottonclub/releases/download/v\d+\.\d+\.\d+/Chrome-vpn-for-cottonclub-Windows-x64\.zip$') { throw 'Unexpected download origin' }
    if ($global:CottonClubBootstrapDownloadMode -eq 'offline') { throw 'Simulated network failure' }
    Copy-Item -LiteralPath $archivePath -Destination $OutFile
}
try {
    foreach ($file in @('Install.ps1','Bootstrap.ps1','release.json')) { Copy-Item (Join-Path $projectRoot $file) $fixture }
    # Exercise the exact entry point from a source ZIP without making system changes.
    & (Join-Path $fixture 'Install.ps1') -VerifyOnly
    $global:CottonClubBootstrapDownloadMode = 'offline'
    $failed = $false
    try { & (Join-Path $fixture 'Install.ps1') -VerifyOnly } catch { $failed = $_.Exception.Message -match 'Could not download' }
    if (-not $failed) { throw 'Network failure was not rejected.' }
    $global:CottonClubBootstrapDownloadMode = 'good'
    $metadata = Get-Content (Join-Path $fixture 'release.json') -Raw | ConvertFrom-Json
    $metadata.sha256 = '0' * 64
    $metadata | ConvertTo-Json | Set-Content (Join-Path $fixture 'release.json') -Encoding UTF8
    $failed = $false
    try { & (Join-Path $fixture 'Install.ps1') -VerifyOnly } catch { $failed = $_.Exception.Message -match 'SHA-256 mismatch' }
    if (-not $failed) { throw 'Damaged archive was not rejected.' }
    Write-Host 'Bootstrap source entry point, offline error and SHA-256 rejection passed.'
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    if ([IO.Path]::GetDirectoryName($resolved) -eq $buildRoot -and
        [IO.Path]::GetFileName($resolved) -match '^bootstrap-test-[0-9a-f]{32}$' -and
        -not ((Get-Item $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

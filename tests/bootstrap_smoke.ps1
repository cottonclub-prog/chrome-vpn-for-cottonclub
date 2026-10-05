$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $projectRoot 'build'
$fixture = Join-Path $buildRoot ('bootstrap-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture -Force | Out-Null
$archivePath = Join-Path $projectRoot 'dist/cottonclub-vpn-for-chrome-windows-x64.zip'
$global:CottonClubBootstrapDownloadMode = 'good'
function Invoke-RestMethod {
    param([string]$Uri, $Headers, [int]$TimeoutSec)
    if ($Uri -ne 'https://api.github.com/repos/cottonclub-prog/chrome-vpn-for-cottonclub/releases/latest') { throw 'Unexpected API origin' }
    return $global:CottonClubBootstrapTestRelease
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [int]$TimeoutSec)
    if ($Uri -notmatch '^https://github\.com/cottonclub-prog/chrome-vpn-for-cottonclub/releases/download/v\d+\.\d+\.\d+/cottonclub-vpn-for-chrome-windows-x64\.zip$') { throw 'Unexpected download origin' }
    if ($global:CottonClubBootstrapDownloadMode -eq 'offline') { throw 'Simulated network failure' }
    Copy-Item -LiteralPath $archivePath -Destination $OutFile
}
try {
    foreach ($file in @('Install.ps1','Bootstrap.ps1')) { Copy-Item (Join-Path $projectRoot $file) $fixture }
    '{"version":"1.1.0","sha256":null}' | Set-Content (Join-Path $fixture 'release.json') -Encoding UTF8
    $failed = $false
    try { & (Join-Path $fixture 'Install.ps1') -VerifyOnly } catch { $failed = $_.Exception.Message -match 'not been published' }
    if (-not $failed) { throw 'Unpublished source build was not rejected.' }
    Copy-Item (Join-Path $projectRoot 'dist/release.json') (Join-Path $fixture 'release.json')
    # Exercise the exact entry point from a source ZIP without making system changes.
    & (Join-Path $fixture 'Install.ps1') -VerifyOnly
    $published = Get-Content (Join-Path $fixture 'release.json') -Raw | ConvertFrom-Json
    $global:CottonClubBootstrapTestRelease = [pscustomobject]@{
        tag_name = 'v' + $published.version; draft = $false; prerelease = $false
        assets = @([pscustomobject]@{ name='cottonclub-vpn-for-chrome-windows-x64.zip'; digest=('sha256:' + $published.sha256)
            browser_download_url="https://github.com/cottonclub-prog/chrome-vpn-for-cottonclub/releases/download/v$($published.version)/cottonclub-vpn-for-chrome-windows-x64.zip" })
    }
    New-Item -ItemType Directory (Join-Path $fixture 'extension') | Out-Null
    '{"version":"1.0.0"}' | Set-Content (Join-Path $fixture 'extension/manifest.json') -Encoding UTF8
    & (Join-Path $fixture 'Bootstrap.ps1') -Latest -VerifyOnly
    $global:CottonClubBootstrapTestRelease.assets[0].browser_download_url = 'https://example.org/untrusted.zip'
    $failed = $false
    try { & (Join-Path $fixture 'Bootstrap.ps1') -Latest -VerifyOnly } catch { $failed = $_.Exception.Message -match 'Verified official' }
    if (-not $failed) { throw 'Foreign update asset was not rejected.' }
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

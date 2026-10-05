param([switch]$VerifyOnly, [switch]$Latest, [switch]$Quiet)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Source ZIPs contain this bootstrap; built packages contain payload.json instead.
# Download and verify the per-user package. No elevation or build tools needed.
$asset = 'cottonclub-vpn-for-chrome-windows-x64.zip'
if ($Latest) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/cottonclub-prog/cottonclub-vpn-for-chrome/releases/latest' -Headers @{ 'User-Agent'='cottonclub-vpn-for-chrome-updater' } -TimeoutSec 30
    if ($release.draft -or $release.prerelease -or $release.tag_name -notmatch '^v\d+\.\d+\.\d+$') { throw 'Invalid stable release.' }
    $version = $release.tag_name.Substring(1)
    $items = @($release.assets | Where-Object { $_.name -eq $asset })
    $expectedUrl = "https://github.com/cottonclub-prog/cottonclub-vpn-for-chrome/releases/download/v$version/$asset"
    if ($items.Count -ne 1 -or $items[0].browser_download_url -ne $expectedUrl -or $items[0].digest -notmatch '^sha256:[0-9a-fA-F]{64}$') { throw 'Verified official update package is missing.' }
    $installed = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([version]$version -le [version]$installed.version) { Write-Host 'The latest version is already installed.'; return }
    $metadata = [pscustomobject]@{ version=$version; sha256=$items[0].digest.Substring(7) }
} else {
    $metadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
}
if (-not $metadata.sha256) {
    throw 'The sing-box package has not been published yet. Run Build.ps1, extract dist/cottonclub-vpn-for-chrome-windows-x64.zip and run Install.cmd inside it.'
}
if ($metadata.version -notmatch '^\d+\.\d+\.\d+$' -or $metadata.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'Invalid release metadata. Download the repository again.'
}
$url = "https://github.com/cottonclub-prog/cottonclub-vpn-for-chrome/releases/download/v$($metadata.version)/$asset"
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$work = [IO.Path]::GetFullPath((Join-Path $tempRoot ('cottonclub-vpn-for-chrome-install-' + [guid]::NewGuid().ToString('N'))))
if ([IO.Path]::GetDirectoryName($work) -ne $tempRoot) { throw 'Invalid temporary directory.' }
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $zip = Join-Path $work $asset
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host "Downloading CottonClub VPN for Chrome $($metadata.version)..."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip -TimeoutSec 180
    } catch {
        throw "Could not download the ready package from GitHub. Check your internet connection and retry Install.cmd. Release: v$($metadata.version)."
    }
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $metadata.sha256) {
        throw 'Downloaded package SHA-256 mismatch. Nothing was installed. Download the repository again and retry.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            $destination = [IO.Path]::GetFullPath((Join-Path $work $entry.FullName))
            if (-not $destination.StartsWith($work + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Unsafe archive path. Nothing was installed.'
            }
        }
    } finally { $archive.Dispose() }
    Expand-Archive -LiteralPath $zip -DestinationPath $work
    $package = Join-Path $work 'cottonclub-vpn-for-chrome'
    foreach ($required in @('Install.ps1','payload.json','CottonClub VPN for Chrome/manifest.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $package $required) -PathType Leaf)) { throw 'Incomplete release archive.' }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $package 'CottonClub VPN for Chrome/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.version -ne $metadata.version) { throw 'Release version mismatch. Nothing was installed.' }
    Write-Host 'Package verified. Preparing installation...'
    $installer = Join-Path $package 'Install.ps1'
    # Run in this PowerShell process; installation never elevates.
    & $installer -VerifyOnly:$VerifyOnly -Quiet:$Quiet

} finally {
    # Only remove the unique directory created by this invocation, never a link.
    $resolved = [IO.Path]::GetFullPath($work)
    if ([IO.Path]::GetDirectoryName($resolved) -eq $tempRoot -and
        [IO.Path]::GetFileName($resolved) -match '^cottonclub-vpn-for-chrome-install-[0-9a-f]{32}$' -and
        (Test-Path -LiteralPath $resolved)) {
        $links = @((Get-Item -LiteralPath $resolved), (Get-ChildItem -LiteralPath $resolved -Recurse -Force)) |
            ForEach-Object { $_ } | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
        if (-not $links) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    }
}

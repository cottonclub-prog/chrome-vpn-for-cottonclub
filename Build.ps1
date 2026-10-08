param([switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'src')
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE) { throw 'Python 3.11 x64 is required for building.' }
    }
    & ./.venv/Scripts/python.exe -m pip install -r requirements.lock
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
    if (-not $SkipDownload) {
        & ./.venv/Scripts/python.exe prepare.py
        if ($LASTEXITCODE) { throw 'sing-box download failed' }
    }
    foreach ($exe in @('bin/sing-box.exe', 'bin/LICENSE-sing-box.txt', 'bin/SOURCE.txt')) {
        if (-not (Test-Path $exe)) { throw "Missing $exe" }
    }
    $stamp = [guid]::NewGuid().ToString('N')
    $output = Join-Path $PSScriptRoot "build/$stamp"
    & ./.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --onedir --console --hide-console hide-early --hidden-import socks --name cottonclub-vpn-for-chrome-host --distpath $output native_host.py
    if ($LASTEXITCODE) { throw 'Native host build failed' }
    $package = Join-Path $PSScriptRoot "dist/$stamp/cottonclub-vpn-for-chrome"
    New-Item -ItemType Directory -Path $package -Force | Out-Null
    Copy-Item (Join-Path $output 'cottonclub-vpn-for-chrome-host') (Join-Path $package 'host') -Recurse
    Copy-Item routing (Join-Path $package 'host') -Recurse
    Copy-Item (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/routing-defaults.json') (Join-Path $package 'host/routing/default-rules.json')
    $coreDirectory = Join-Path $package 'host/bin'
    New-Item -ItemType Directory -Path $coreDirectory -Force | Out-Null
    # Explicit allowlist also excludes stale binaries from previous builds.
    Copy-Item bin/sing-box.exe,bin/LICENSE-sing-box.txt,bin/SOURCE.txt $coreDirectory
    Copy-Item (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome') $package -Recurse
    foreach ($file in @('Install.cmd','Install.ps1','Launch.ps1','Uninstall.cmd','Uninstall.ps1','Bootstrap.ps1','Update.ps1','Diagnose.cmd','Diagnose.ps1','README.md')) {
        Copy-Item (Join-Path $PSScriptRoot $file) $package
    }
    $hashes = @(Get-ChildItem $package -File -Recurse | ForEach-Object {
        @{ path = $_.FullName.Substring($package.Length + 1); sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    })
    $hashes | ConvertTo-Json | Set-Content (Join-Path $package 'payload.json') -Encoding UTF8
    $archive = Join-Path $PSScriptRoot 'dist/cottonclub-vpn-for-chrome-windows-x64.zip'
    Compress-Archive -Path $package -DestinationPath $archive -Force
    $manifest = Get-Content (Join-Path $package 'CottonClub VPN for Chrome/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    @{ version = $manifest.version; sha256 = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() } |
        ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'dist/release.json') -Encoding UTF8
    Write-Host "READY: $archive"
} finally { Pop-Location }

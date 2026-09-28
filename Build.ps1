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
        & ./.venv/Scripts/python.exe prepare_xray.py
        if ($LASTEXITCODE) { throw 'Xray download failed' }
    }
    foreach ($exe in @('bin/xray.exe', 'bin/sing-box.exe')) {
        if (-not (Test-Path $exe)) { throw "Missing $exe" }
    }
    $stamp = [guid]::NewGuid().ToString('N')
    $output = Join-Path $PSScriptRoot "build/$stamp"
    & ./.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --onedir --console --hide-console hide-early --hidden-import socks --name ZXC-AdminHost --distpath $output native_host.py
    if ($LASTEXITCODE) { throw 'Native host build failed' }
    $package = Join-Path $PSScriptRoot "dist/$stamp/Chrome-vpn-for-cottonclub"
    New-Item -ItemType Directory -Path $package -Force | Out-Null
    Copy-Item (Join-Path $output 'ZXC-AdminHost') (Join-Path $package 'host') -Recurse
    Copy-Item bin,routing (Join-Path $package 'host') -Recurse
    Copy-Item (Join-Path $PSScriptRoot 'extension') $package -Recurse
    foreach ($file in @('Install.cmd','Install.ps1','Launch.vbs','Launch.ps1','Uninstall.cmd','Uninstall.ps1','README.md')) {
        Copy-Item (Join-Path $PSScriptRoot $file) $package
    }
    $hashes = @(Get-ChildItem $package -File -Recurse | ForEach-Object {
        @{ path = $_.FullName.Substring($package.Length + 1); sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    })
    $hashes | ConvertTo-Json | Set-Content (Join-Path $package 'payload.json') -Encoding UTF8
    $archive = Join-Path $PSScriptRoot 'dist/Chrome-vpn-for-cottonclub-Windows-x64.zip'
    Compress-Archive -Path $package -DestinationPath $archive -Force
    Write-Host "READY: $archive"
} finally { Pop-Location }

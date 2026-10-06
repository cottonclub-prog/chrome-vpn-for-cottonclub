param([string]$KeyPath = (Join-Path $PSScriptRoot '.keys/cottonclub-crx.pem'))
$ErrorActionPreference = 'Stop'
$archive = Join-Path $PSScriptRoot 'dist/cottonclub-vpn-for-chrome-windows-x64.zip'
$metadata = Get-Content (Join-Path $PSScriptRoot 'dist/release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest = Get-Content (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($metadata.version -ne $manifest.version -or (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $metadata.sha256) {
    throw 'Run Build.ps1 first: package version or SHA-256 does not match.'
}
if (-not (Test-Path -LiteralPath $KeyPath)) { throw 'CRX signing PEM is missing. Keep it outside Git and use the same key for all CRX updates.' }
$KeyPath = [IO.Path]::GetFullPath($KeyPath)
$stage = Join-Path $PSScriptRoot ('build/distribution-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$extensionPath = Join-Path $stage 'CottonClub VPN for Chrome'
Copy-Item (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome') $extensionPath -Recurse
$identity = Get-Content (Join-Path $PSScriptRoot 'installer/crx-identity.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest.key = $identity.key
$manifest | Add-Member -NotePropertyName update_url -NotePropertyValue 'https://github.com/cottonclub-prog/cottonclub-vpn-for-chrome/releases/latest/download/updates.xml' -Force
$manifest | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $extensionPath 'manifest.json') -Encoding UTF8
$chromePath = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chromePath) { throw 'Google Chrome is required to produce CRX3.' }
$arguments = @('--headless=new', '--no-first-run', '--no-default-browser-check', '--no-message-box', ('--user-data-dir="' + (Join-Path $stage 'chrome-profile') + '"'), ('--pack-extension="' + $extensionPath + '"'), ('--pack-extension-key="' + $KeyPath + '"'))
$packer = Start-Process -FilePath $chromePath -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
if ($packer.ExitCode -ne 0 -or -not (Test-Path ($extensionPath + '.crx'))) { throw 'Chrome CRX packing failed.' }
$crxPath = Join-Path $PSScriptRoot 'dist/cottonclub-vpn-for-chrome.crx'
Copy-Item -LiteralPath ($extensionPath + '.crx') -Destination $crxPath -Force
& node (Join-Path $PSScriptRoot 'installer/verify-crx.cjs') $crxPath $identity.id
if ($LASTEXITCODE) { throw 'CRX signature or identity verification failed.' }
$updates = '<?xml version="1.0" encoding="UTF-8"?><gupdate xmlns="http://www.google.com/update2/response" protocol="2.0"><app appid="' + $identity.id + '"><updatecheck codebase="https://github.com/cottonclub-prog/cottonclub-vpn-for-chrome/releases/download/v' + $metadata.version + '/cottonclub-vpn-for-chrome.crx" version="' + $metadata.version + '" /></app></gupdate>'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dist/updates.xml'), $updates, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $stage 'payload.sha256'), $metadata.sha256, [Text.UTF8Encoding]::new($false))
$iconPath = Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/icons/app.ico'
$versionSource = Join-Path $stage 'AssemblyInfo.cs'
[IO.File]::WriteAllText($versionSource, ('[assembly:System.Reflection.AssemblyTitle("CottonClub VPN for Chrome Setup")][assembly:System.Reflection.AssemblyFileVersion("' + $metadata.version + '.0")]'), [Text.UTF8Encoding]::new($false))
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$setupPath = Join-Path $PSScriptRoot ('dist/cottonclub-vpn-for-chrome-setup-' + $metadata.version + '.exe')
& $compiler /nologo /target:winexe /platform:x64 "/out:$setupPath" "/win32icon:$iconPath" "/win32manifest:$(Join-Path $PSScriptRoot 'installer/app.manifest')" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/resource:$archive,payload.zip" "/resource:$(Join-Path $stage 'payload.sha256'),payload.sha256" (Join-Path $PSScriptRoot 'installer/Setup.cs') $versionSource
if ($LASTEXITCODE) { throw 'EXE installer compilation failed.' }
@($archive,$crxPath,$setupPath,(Join-Path $PSScriptRoot 'dist/updates.xml')) | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLower() + '  ' + [IO.Path]::GetFileName($_)
} | Set-Content (Join-Path $PSScriptRoot 'dist/SHA256SUMS.txt') -Encoding ASCII
Write-Output "READY: $setupPath"
Write-Output "READY: $crxPath"
Write-Output ('CRX ID: ' + $identity.id)

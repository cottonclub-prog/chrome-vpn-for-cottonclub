param([string]$KeyPath = (Join-Path $PSScriptRoot '.keys/cottonclub-crx.pem'))
$ErrorActionPreference = 'Stop'
$archive = Join-Path $PSScriptRoot 'dist/Chrome-vpn-for-cottonclub-hysteria2-user-Windows-x64.zip'
$metadata = Get-Content (Join-Path $PSScriptRoot 'dist/release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest = Get-Content (Join-Path $PSScriptRoot 'extension/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($metadata.version -ne $manifest.version -or (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $metadata.sha256) {
    throw 'Run Build.ps1 first: package version or SHA-256 does not match.'
}
if (-not (Test-Path -LiteralPath $KeyPath)) { throw 'CRX signing PEM is missing. Keep it outside Git and use the same key for all CRX updates.' }
$KeyPath = [IO.Path]::GetFullPath($KeyPath)
$stage = Join-Path $PSScriptRoot ('build/distribution-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$extensionPath = Join-Path $stage 'extension'
Copy-Item (Join-Path $PSScriptRoot 'extension') $extensionPath -Recurse
$identity = Get-Content (Join-Path $PSScriptRoot 'installer/crx-identity.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest.key = $identity.key
$manifest | Add-Member -NotePropertyName update_url -NotePropertyValue 'https://github.com/cottonclub-prog/chrome-vpn-for-cottonclub/releases/latest/download/updates.xml' -Force
$manifest | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $extensionPath 'manifest.json') -Encoding UTF8
$chromePath = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chromePath) { throw 'Google Chrome is required to produce CRX3.' }
$arguments = @('--headless=new', '--no-first-run', '--no-default-browser-check', '--no-message-box', ('--user-data-dir="' + (Join-Path $stage 'chrome-profile') + '"'), ('--pack-extension="' + $extensionPath + '"'), ('--pack-extension-key="' + $KeyPath + '"'))
$packer = Start-Process -FilePath $chromePath -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
if ($packer.ExitCode -ne 0 -or -not (Test-Path ($extensionPath + '.crx'))) { throw 'Chrome CRX packing failed.' }
$crxPath = Join-Path $PSScriptRoot 'dist/COTTONCLUB-VPN.crx'
Copy-Item -LiteralPath ($extensionPath + '.crx') -Destination $crxPath -Force
& node (Join-Path $PSScriptRoot 'installer/verify-crx.cjs') $crxPath $identity.id
if ($LASTEXITCODE) { throw 'CRX signature or identity verification failed.' }
$updates = '<?xml version="1.0" encoding="UTF-8"?><gupdate xmlns="http://www.google.com/update2/response" protocol="2.0"><app appid="' + $identity.id + '"><updatecheck codebase="https://github.com/cottonclub-prog/chrome-vpn-for-cottonclub/releases/download/v' + $metadata.version + '/COTTONCLUB-VPN.crx" version="' + $metadata.version + '" /></app></gupdate>'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dist/updates.xml'), $updates, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $stage 'payload.sha256'), $metadata.sha256, [Text.UTF8Encoding]::new($false))
$iconPath = Join-Path $stage 'setup.ico'
$iconStream = [IO.File]::Create($iconPath)
$writer = [IO.BinaryWriter]::new($iconStream)
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]4)
    $offset = 6 + 4 * 16
    foreach ($size in @(16,32,48,128)) {
        $bytes = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot "extension/icons/icon-$size.png"))
        $writer.Write([byte]$size); $writer.Write([byte]$size); $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32); $writer.Write([uint32]$bytes.Length); $writer.Write([uint32]$offset)
        $offset += $bytes.Length
    }
    foreach ($size in @(16,32,48,128)) { $writer.Write([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot "extension/icons/icon-$size.png"))) }
} finally { $writer.Dispose(); $iconStream.Dispose() }
$versionSource = Join-Path $stage 'AssemblyInfo.cs'
[IO.File]::WriteAllText($versionSource, ('[assembly:System.Reflection.AssemblyTitle("COTTONCLUB VPN Setup")][assembly:System.Reflection.AssemblyFileVersion("' + $metadata.version + '.0")]'), [Text.UTF8Encoding]::new($false))
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$setupPath = Join-Path $PSScriptRoot ('dist/COTTONCLUB-VPN-Setup-' + $metadata.version + '.exe')
& $compiler /nologo /target:winexe /platform:x64 "/out:$setupPath" "/win32icon:$iconPath" "/win32manifest:$(Join-Path $PSScriptRoot 'installer/app.manifest')" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/resource:$archive,payload.zip" "/resource:$(Join-Path $stage 'payload.sha256'),payload.sha256" (Join-Path $PSScriptRoot 'installer/Setup.cs') $versionSource
if ($LASTEXITCODE) { throw 'EXE installer compilation failed.' }
@($archive,$crxPath,$setupPath,(Join-Path $PSScriptRoot 'dist/updates.xml')) | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLower() + '  ' + [IO.Path]::GetFileName($_)
} | Set-Content (Join-Path $PSScriptRoot 'dist/SHA256SUMS.txt') -Encoding ASCII
Write-Output "READY: $setupPath"
Write-Output "READY: $crxPath"
Write-Output ('CRX ID: ' + $identity.id)

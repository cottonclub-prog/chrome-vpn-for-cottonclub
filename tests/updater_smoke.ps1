$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$fixture = Join-Path $projectRoot ('build/updater-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $fixture 'CottonClub VPN for Chrome') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'Update.ps1') -Destination $fixture
$requestId = '12345678901234567890123456789012'
$bootstrap = Join-Path $fixture 'Bootstrap.ps1'
@'
param([switch]$Latest, [switch]$Quiet)
if (-not $Latest -or -not $Quiet) { throw 'Updater must request a noninteractive latest install.' }
'{"version":"1.2.2"}' | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/manifest.json') -Encoding UTF8
'@ | Set-Content -LiteralPath $bootstrap -Encoding UTF8
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture 'Update.ps1') -UpdateId $requestId
if ($LASTEXITCODE -ne 0) { throw 'Successful update failed.' }
$status = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $fixture 'CottonClub VPN for Chrome/update-status.json') | ConvertFrom-Json
if ($status.id -ne $requestId -or $status.phase -ne 'complete' -or $status.version -ne '1.2.2') { throw 'Installed version was not confirmed.' }
'param([switch]$Latest, [switch]$Quiet); throw "Simulated download failure"' | Set-Content -LiteralPath $bootstrap -Encoding UTF8
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture 'Update.ps1') -UpdateId $requestId
if ($LASTEXITCODE -eq 0) { throw 'Failed update returned success.' }
$status = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $fixture 'CottonClub VPN for Chrome/update-status.json') | ConvertFrom-Json
if ($status.phase -ne 'failed' -or $status.message -notmatch 'Simulated download failure') { throw 'Update failure was not reported.' }
Write-Output 'Updater completion, installed version and error reporting passed without installation.'

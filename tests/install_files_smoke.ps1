$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$fixture = Join-Path $projectRoot ('build/install-files-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture -Force | Out-Null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'Install.ps1'), [ref]$null, [ref]$parseErrors)
if ($parseErrors) { throw 'Installer syntax is invalid.' }
# Load only file-management functions: no HKCU, shortcuts or actual installation.
foreach ($name in @('Test-InstallDirectory','Install-ApplicationFiles','Remove-PreviousApplicationFiles')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}
$package = Join-Path $fixture 'payload'
New-Item -ItemType Directory -Path (Join-Path $package 'host'),(Join-Path $package 'extension') -Force | Out-Null
'new host' | Set-Content -LiteralPath (Join-Path $package 'host/cottonclub-vpn-for-chrome-host.exe')
'{"version":"1.6.0"}' | Set-Content -LiteralPath (Join-Path $package 'extension/manifest.json')
foreach ($file in @('Launch.ps1','Uninstall.cmd','Uninstall.ps1','Bootstrap.ps1','Update.ps1','README.md')) { 'fixture' | Set-Content -LiteralPath (Join-Path $package $file) }
$parent = Join-Path $fixture 'localappdata'
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$old = Join-Path $parent 'Chrome VPN for CottonClub'
$oldIdentity = Join-Path $parent 'ZXC-Desktop'
$oldRuntime = Join-Path $parent 'CottonClub-Hysteria2'
$release = Join-Path $old 'releases/1234567890abcdef1234567890abcdef'
New-Item -ItemType Directory -Path (Join-Path $release 'host'),$oldIdentity,(Join-Path $oldRuntime 'extension') -Force | Out-Null
'old host' | Set-Content -LiteralPath (Join-Path $release 'host/CottonClub-Host.exe')
'{"name":"com.cottonclub.hysteria2"}' | Set-Content -LiteralPath (Join-Path $release 'com.cottonclub.hysteria2.json')
'retained user file' | Set-Content -LiteralPath (Join-Path $old 'user-note.txt')
$identity = '0123456789abcdef0123456789abcdef'
[IO.File]::WriteAllText((Join-Path $oldIdentity 'device-id.txt'), $identity)
$base = Install-ApplicationFiles $package $parent
Remove-PreviousApplicationFiles $base $parent
if ($base -ne (Join-Path $parent 'cottonclub vpn for chrome')) { throw 'Unexpected install folder' }
if ([IO.File]::ReadAllText((Join-Path $base 'device-id.txt')) -cne $identity) { throw 'Device identity changed' }
if ((Test-Path $old) -or (Test-Path $oldIdentity) -or (Test-Path $oldRuntime) -or (Test-Path (Join-Path $base 'releases'))) { throw 'Previous generated directories remain' }
if (-not (Test-Path (Join-Path $base 'user-note.txt'))) { throw 'User file was not preserved' }
'updated host' | Set-Content -LiteralPath (Join-Path $package 'host/cottonclub-vpn-for-chrome-host.exe')
$again = Install-ApplicationFiles $package $parent
Remove-PreviousApplicationFiles $again $parent
if ((Get-Content -LiteralPath (Join-Path $base 'host/cottonclub-vpn-for-chrome-host.exe')).Trim() -ne 'updated host') { throw 'Helper was not updated in place' }
if ([IO.File]::ReadAllText((Join-Path $base 'device-id.txt')) -cne $identity) { throw 'Update replaced identity' }
if (@(Get-ChildItem -LiteralPath $base -Directory).Count -ne 2) { throw 'Update accumulated directories' }
# A malformed previous identity must fail before creating or moving installation files.
$badParent = Join-Path $fixture 'invalid'
New-Item -ItemType Directory -Path (Join-Path $badParent 'ZXC-Desktop') -Force | Out-Null
'invalid' | Set-Content -LiteralPath (Join-Path $badParent 'ZXC-Desktop/device-id.txt')
$failed = $false
try { Install-ApplicationFiles $package $badParent } catch { $failed = $_.Exception.Message -match 'Invalid saved device' }
if (-not $failed -or (Test-Path (Join-Path $badParent 'cottonclub vpn for chrome'))) { throw 'Malformed identity was not rejected safely' }
# Simulate an active helper using only a mock process record.
function Get-Process { param($Name, $ErrorAction); [pscustomobject]@{Path=(Join-Path $base 'host/cottonclub-vpn-for-chrome-host.exe')} }
$failed = $false
try { Install-ApplicationFiles $package $parent } catch { $failed = $_.Exception.Message -match 'Disable cottonclub' }
if (-not $failed) { throw 'An active helper was not rejected' }
Write-Output 'Migration, preserved identity/files, repeated updates, compact directories and active-helper refusal passed in workspace fixtures.'

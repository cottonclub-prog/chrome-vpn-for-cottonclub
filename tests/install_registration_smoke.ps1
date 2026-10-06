$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$fixture = Join-Path $projectRoot ('build/install-registration-test-' + [guid]::NewGuid().ToString('N'))
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'Install.ps1'), [ref]$null, [ref]$parseErrors)
if ($parseErrors) { throw 'Installer syntax is invalid.' }
# Import only cleanup functions; registry and shortcut metadata are simulated.
foreach ($name in @('Test-InstallDirectory', 'Remove-WindowsApplicationEntries')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}
$parent = Join-Path $fixture 'localappdata'
$base = Join-Path $parent 'CottonClub VPN for Chrome'
$desktop = Join-Path $fixture 'desktop'
$programs = Join-Path $fixture 'programs'
New-Item -ItemType Directory -Path $base,$desktop,$programs -Force | Out-Null
$prefix = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\'
$nativeKey = 'Software\Google\Chrome\NativeMessagingHosts\com.cottonclub.hysteria2'
$registry = [pscustomobject]@{Entries=@{}; Deleted=[Collections.Generic.List[string]]::new()}
$registry | Add-Member ScriptMethod OpenSubKey {
    param($path)
    if (-not $this.Entries.ContainsKey($path)) { return $null }
    $record = [pscustomobject]@{Values=$this.Entries[$path]}
    $record | Add-Member ScriptMethod GetValue { param($name) return $this.Values[$name] }
    $record | Add-Member ScriptMethod Close {}
    return $record
}
$registry | Add-Member ScriptMethod DeleteSubKeyTree {
    param($path, $throwOnMissing)
    $this.Deleted.Add($path)
    $this.Entries.Remove($path)
}
$shell = [pscustomobject]@{Links=@{}; Read=[Collections.Generic.List[string]]::new()}
$shell | Add-Member ScriptMethod CreateShortcut {
    param($path)
    if (-not $this.Links.ContainsKey($path)) { throw 'Missing shortcut metadata' }
    $this.Read.Add($path)
    return $this.Links[$path]
}
function Add-TestShortcut([string]$Path, [string]$Target, [string]$Arguments) {
    'fixture shortcut' | Set-Content -LiteralPath $Path
    $link = [pscustomobject]@{TargetPath=$Target; Arguments=$Arguments}
    $link | Add-Member ScriptMethod Save { throw 'Installer must never write shortcuts' }
    $shell.Links[$Path] = $link
}
function Assert-OnlyNativeRegistration {
    if ($registry.Entries.Count -ne 1 -or $registry.Entries[$nativeKey] -ne 'preserved host') { throw 'Native Messaging registration changed' }
}
$registry.Entries[$nativeKey] = 'preserved host'
Remove-WindowsApplicationEntries $base $registry $shell @($desktop,$programs)
Assert-OnlyNativeRegistration
if ($registry.Deleted.Count -or $shell.Read.Count -or (Get-ChildItem $desktop,$programs -Force)) { throw 'Fresh installation created application entries or shortcuts' }

# Current and legacy owned registrations disappear during an upgrade.
$registry.Entries[$prefix + 'CottonClubVpnForChrome'] = @{InstallLocation=$base}
$legacy = Join-Path $parent 'CottonClub-Hysteria2'
$registry.Entries[$prefix + 'CottonClubHysteria2'] = @{UninstallString='powershell.exe -File "' + (Join-Path $legacy 'Uninstall.ps1') + '"'}
foreach ($folder in @($desktop,$programs)) {
    Add-TestShortcut (Join-Path $folder 'CottonClub VPN for Chrome.lnk') 'powershell.exe' ('-File "' + (Join-Path $base 'Launch.ps1') + '"')
    Add-TestShortcut (Join-Path $folder 'CottonClub Hysteria 2.lnk') (Join-Path $legacy 'Launch.cmd') ''
}
'user file' | Set-Content -LiteralPath (Join-Path $desktop 'keep.txt')
Remove-WindowsApplicationEntries $base $registry $shell @($desktop,$programs)
Assert-OnlyNativeRegistration
if ($registry.Deleted.Count -ne 2 -or (Get-ChildItem $desktop,$programs -Filter '*.lnk')) { throw 'Owned application entries were not removed' }
if (-not (Test-Path -LiteralPath (Join-Path $desktop 'keep.txt'))) { throw 'Unrelated file removed' }
Remove-WindowsApplicationEntries $base $registry $shell @($desktop,$programs)
if ($registry.Deleted.Count -ne 2) { throw 'Repeated cleanup is not idempotent' }

# An identically named entry for a different location is not ours.
$unrelated = Join-Path $fixture 'unrelated'
$registry.Entries[$prefix + 'CottonClubVpnForChrome'] = @{InstallLocation=$unrelated; UninstallString='powershell.exe -File "' + (Join-Path $base 'Uninstall.ps1') + '"'}
$registry.Entries[$prefix + 'CottonClubHysteria2'] = @{UninstallString='powershell.exe -File "' + (Join-Path ($base + '-other') 'Uninstall.ps1') + '"'}
Add-TestShortcut (Join-Path $desktop 'CottonClub VPN for Chrome.lnk') (Join-Path ($base + '-other') 'Launch.cmd') ''
Add-TestShortcut (Join-Path $programs 'CottonClub Hysteria 2.lnk') 'powershell.exe' ('-File "' + (Join-Path $unrelated 'Launch.ps1') + '"')
Remove-WindowsApplicationEntries $base $registry $shell @($desktop,$programs)
if ($registry.Deleted.Count -ne 2 -or $registry.Entries.Count -ne 3 -or @(Get-ChildItem $desktop,$programs -Filter '*.lnk').Count -ne 2) { throw 'Unrelated registration or shortcut removed' }

# Older registration using the previous installation folder is recognized too.
$registry.Entries[$prefix + 'CottonClubVpnForChrome'] = @{InstallLocation=(Join-Path $parent 'Chrome VPN for CottonClub')}
Remove-WindowsApplicationEntries $base $registry $shell @($desktop,$programs)
if ($registry.Entries.ContainsKey($prefix + 'CottonClubVpnForChrome') -or $registry.Entries[$nativeKey] -ne 'preserved host') { throw 'Previous installation registration cleanup failed' }
Write-Output 'Fresh installation, owned legacy/current cleanup, repeated updates, unrelated entries and Native Messaging preservation passed in isolated fixtures.'

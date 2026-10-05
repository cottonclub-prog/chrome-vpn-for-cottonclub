param([switch]$VerifyOnly, [switch]$Quiet, [switch]$AllowMigration)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Test-InstallDirectory([string]$Path, [string]$Parent, [string]$Name) {
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($resolved) -ne [IO.Path]::GetFullPath($Parent).TrimEnd('\') -or [IO.Path]::GetFileName($resolved) -ne $Name) { throw 'Invalid installation directory' }
    if (Test-Path -LiteralPath $resolved) {
        if ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation directory must not be a link.' }
        if (Get-ChildItem -LiteralPath $resolved -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Installation contents must not contain links.' }
    }
}
function Install-ApplicationFiles([string]$Package, [string]$Parent) {
    $base = Join-Path $Parent 'CottonClub VPN for Chrome'
    $previous = Join-Path $Parent 'Chrome VPN for CottonClub'
    # Previous names are read only for a one-time migration, never created.
    $identityDirectory = Join-Path $Parent 'ZXC-Desktop'
    $runtimeDirectory = Join-Path $Parent 'CottonClub-Hysteria2'
    Test-InstallDirectory $base $Parent 'CottonClub VPN for Chrome'
    Test-InstallDirectory $previous $Parent 'Chrome VPN for CottonClub'
    Test-InstallDirectory $identityDirectory $Parent 'ZXC-Desktop'
    Test-InstallDirectory $runtimeDirectory $Parent 'CottonClub-Hysteria2'
    foreach ($process in @(Get-Process cottonclub-vpn-for-chrome-host,CottonClub-Host,sing-box -ErrorAction SilentlyContinue)) {
        if ($process.Path -and ($process.Path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase) -or $process.Path.StartsWith($previous + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Disable CottonClub VPN for Chrome in chrome://extensions before updating, then run Install.cmd again.' }
    }
    if ((Test-Path -LiteralPath $previous) -and (Test-Path -LiteralPath $base)) { throw 'Both old and new installation directories exist. Keep the installation you use before retrying.' }
    $identity = Join-Path $identityDirectory 'device-id.txt'
    if (Test-Path -LiteralPath $identity) {
        $savedIdentity = [IO.File]::ReadAllText($identity).Trim()
        if ($savedIdentity -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid saved device identifier; migration cancelled.' }
    }
    foreach ($installation in @($base, $previous)) {
        $existingIdentity = Join-Path $installation 'device-id.txt'
        if ((Test-Path -LiteralPath $existingIdentity) -and [IO.File]::ReadAllText($existingIdentity).Trim() -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid saved device identifier; migration cancelled.' }
    }
    if (Test-Path -LiteralPath $previous) { Move-Item -LiteralPath $previous -Destination $base }
    if ((Test-Path -LiteralPath $base) -and (Get-Item -LiteralPath $base).Name -cne 'CottonClub VPN for Chrome') { Rename-Item -LiteralPath $base -NewName 'CottonClub VPN for Chrome' }
    New-Item -ItemType Directory -Path $base -Force | Out-Null
    $previousExtension = Join-Path $base 'extension'
    $extension = Join-Path $base 'CottonClub VPN for Chrome'
    if ((Test-Path -LiteralPath $previousExtension) -and (Test-Path -LiteralPath $extension)) { throw 'Both old and new extension directories exist. Keep the extension directory you use before retrying.' }
    if (Test-Path -LiteralPath $previousExtension) { Move-Item -LiteralPath $previousExtension -Destination $extension }
    $device = Join-Path $base 'device-id.txt'
    if ($savedIdentity -and -not (Test-Path -LiteralPath $device)) { [IO.File]::WriteAllText($device, $savedIdentity, [Text.Encoding]::ASCII) }
    $previousProfile = Join-Path $runtimeDirectory 'chrome-profile'
    if ((Test-Path -LiteralPath $previousProfile) -and -not (Test-Path -LiteralPath (Join-Path $base 'chrome-profile'))) { Move-Item -LiteralPath $previousProfile -Destination (Join-Path $base 'chrome-profile') }
    # The helper is stopped above; a fixed host directory avoids release accumulation.
    Copy-Item -LiteralPath (Join-Path $Package 'host') -Destination $base -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $Package 'CottonClub VPN for Chrome') -Destination $base -Recurse -Force
    [IO.File]::WriteAllText((Join-Path $base 'CottonClub VPN for Chrome/managed-install.json'), '{"managed":true}', [Text.UTF8Encoding]::new($false))
    foreach ($file in @('Launch.ps1','Uninstall.cmd','Uninstall.ps1','Bootstrap.ps1','Update.ps1','README.md')) { Copy-Item -LiteralPath (Join-Path $Package $file) -Destination $base -Force }
    return $base
}
function Remove-PreviousApplicationFiles([string]$Base, [string]$Parent) {
    Test-InstallDirectory $Base $Parent 'CottonClub VPN for Chrome'
    # Delete only recognizable generated releases belonging to this installation.
    $releases = Join-Path $Base 'releases'
    if (Test-Path -LiteralPath $releases) {
        foreach ($release in @(Get-ChildItem -LiteralPath $releases -Directory)) {
            $registration = Join-Path $release.FullName 'com.cottonclub.hysteria2.json'
            if ($release.Name -match '^[a-f0-9]{32}$' -and (Test-Path -LiteralPath $registration)) {
                $metadata = Get-Content -LiteralPath $registration -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($metadata.name -eq 'com.cottonclub.hysteria2' -and (Test-Path -LiteralPath (Join-Path $release.FullName 'host/CottonClub-Host.exe'))) { Remove-Item -LiteralPath $release.FullName -Recurse -Force }
            }
        }
        if (-not (Get-ChildItem -LiteralPath $releases -Force)) { Remove-Item -LiteralPath $releases }
    }
    $identityDirectory = Join-Path $Parent 'ZXC-Desktop'
    Test-InstallDirectory $identityDirectory $Parent 'ZXC-Desktop'
    $identity = Join-Path $identityDirectory 'device-id.txt'
    $device = Join-Path $Base 'device-id.txt'
    if ((Test-Path -LiteralPath $identity) -and (Test-Path -LiteralPath $device) -and [IO.File]::ReadAllText($identity).Trim() -ceq [IO.File]::ReadAllText($device).Trim()) {
        Remove-Item -LiteralPath $identity
        if (-not (Get-ChildItem -LiteralPath $identityDirectory -Force)) { Remove-Item -LiteralPath $identityDirectory }
    }
    $runtimeDirectory = Join-Path $Parent 'CottonClub-Hysteria2'
    Test-InstallDirectory $runtimeDirectory $Parent 'CottonClub-Hysteria2'
    $previousTemporary = Join-Path $runtimeDirectory 'extension'
    if ((Test-Path -LiteralPath $previousTemporary) -and -not (Get-ChildItem -LiteralPath $previousTemporary -Force)) { Remove-Item -LiteralPath $previousTemporary }
    if ((Test-Path -LiteralPath $runtimeDirectory) -and -not (Get-ChildItem -LiteralPath $runtimeDirectory -Force)) { Remove-Item -LiteralPath $runtimeDirectory }
}
function Test-Package {
    if (-not (Test-Path (Join-Path $PSScriptRoot 'payload.json'))) { throw 'Run Install.cmd from the built ZIP in dist, not the source folder.' }
    $files = Get-Content (Join-Path $PSScriptRoot 'payload.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $listed = @{}
    foreach ($item in $files) {
        $source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $item.path))
        if (-not $source.StartsWith($PSScriptRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid payload path' }
        if ($listed.ContainsKey($source)) { throw 'Duplicate payload path' }
        $listed[$source] = $true
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $item.sha256) { throw "Damaged package: $($item.path)" }
    }
    foreach ($required in @('host/cottonclub-vpn-for-chrome-host.exe','host/bin/sing-box.exe','CottonClub VPN for Chrome/manifest.json','Install.ps1','Launch.ps1','Uninstall.ps1','Uninstall.cmd','README.md')) {
        if (-not $listed.ContainsKey([IO.Path]::GetFullPath((Join-Path $PSScriptRoot $required)))) { throw "Incomplete package: $required" }
    }
    foreach ($entry in (Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -Force)) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package must not contain links.' }
        if (-not $entry.PSIsContainer -and $entry.FullName -ne (Join-Path $PSScriptRoot 'payload.json') -and -not $listed.ContainsKey($entry.FullName)) { throw "Unlisted package file: $($entry.Name)" }
    }
    $manifest = Get-Content (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $hash = [Security.Cryptography.SHA256]::Create().ComputeHash([Convert]::FromBase64String($manifest.key))
    $id = -join ($hash[0..15] | ForEach-Object { [char](97 + ($_ -shr 4)); [char](97 + ($_ -band 15)) })
    if ($id -ne 'hooimhadihhgfkhidbmjoaojfljafnaf') { throw 'Extension identity mismatch' }
    return $manifest
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'payload.json'))) {
        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'Bootstrap.ps1')) {
            & (Join-Path $PSScriptRoot 'Bootstrap.ps1') -VerifyOnly:$VerifyOnly -Quiet:$Quiet
            return
        }
        throw 'Incomplete installation package. Extract the whole ZIP or download the repository again.'
    }
    $manifest = Test-Package
    if ($VerifyOnly) { Write-Host 'Package verified; no system changes made.'; return }
    $parent = [Environment]::GetFolderPath('LocalApplicationData')
    if ($Quiet -and -not $AllowMigration -and ((Test-Path -LiteralPath (Join-Path $parent 'Chrome VPN for CottonClub')) -or (Test-Path -LiteralPath (Join-Path $parent 'CottonClub VPN for Chrome/extension')))) { throw 'The installation folder has changed. Run the new cottonclub-vpn-for-chrome EXE or Install.cmd manually, then load %LOCALAPPDATA%\CottonClub VPN for Chrome\CottonClub VPN for Chrome in chrome://extensions without removing the extension.' }
    $base = Install-ApplicationFiles $PSScriptRoot $parent
    $id = 'hooimhadihhgfkhidbmjoaojfljafnaf'
    $hostPath = Join-Path $base 'com.cottonclub.hysteria2.json'
    $hostJson = @{name='com.cottonclub.hysteria2'; description='CottonClub VPN for Chrome'; path=(Join-Path $base 'host/cottonclub-vpn-for-chrome-host.exe'); type='stdio'; allowed_origins=@("chrome-extension://$id/", 'chrome-extension://pppgaipmgmbndhejmkabemifkonbgooh/')} | ConvertTo-Json
    [IO.File]::WriteAllText($hostPath, $hostJson, [Text.UTF8Encoding]::new($false))
    $hkcu = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $key = $hkcu.CreateSubKey('Software\Google\Chrome\NativeMessagingHosts\com.cottonclub.hysteria2')
        try { $key.SetValue('', $hostPath) } finally { $key.Close() }
        $uninstall = $hkcu.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\CottonClubVpnForChrome')
        try {
            $uninstall.SetValue('DisplayName', 'CottonClub VPN for Chrome')
            $uninstall.SetValue('DisplayVersion', $manifest.version)
            $uninstall.SetValue('InstallLocation', $base)
            $uninstall.SetValue('UninstallString', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $base 'Uninstall.ps1') + '"')
        } finally { $uninstall.Close() }
        $hkcu.DeleteSubKeyTree('Software\Microsoft\Windows\CurrentVersion\Uninstall\CottonClubHysteria2', $false)
    } finally { $hkcu.Close() }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))) {
        $previousShortcut = Join-Path $folder 'CottonClub Hysteria 2.lnk'
        if (Test-Path -LiteralPath $previousShortcut) { Remove-Item -LiteralPath $previousShortcut }
        $shortcut = $shell.CreateShortcut((Join-Path $folder 'CottonClub VPN for Chrome.lnk'))
        $shortcut.TargetPath = Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $base 'Launch.ps1') + '"'
        $shortcut.WindowStyle = 7
        $shortcut.WorkingDirectory = $base
        $shortcut.Save()
    }
    Remove-PreviousApplicationFiles $base $parent
    if ($Quiet) { Write-Host "Installed version $($manifest.version)."; return }
    Add-Type -AssemblyName System.Windows.Forms
    $message = "Installed for your Windows account, without administrator rights. In chrome://extensions enable Developer mode, click Load unpacked and select:`n$base\CottonClub VPN for Chrome`nAfter migrating from an earlier version, select this new folder without removing the extension. Later updates only need a reload."
    [Windows.Forms.MessageBox]::Show($message, 'CottonClub VPN for Chrome') | Out-Null
} catch {
    if ($VerifyOnly -or $Quiet) { throw }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'CottonClub VPN for Chrome installation failed') | Out-Null
    throw
}

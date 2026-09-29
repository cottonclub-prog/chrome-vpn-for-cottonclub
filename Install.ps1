param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
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
    foreach ($required in @('host/CottonClub-Host.exe','host/bin/sing-box.exe','extension/manifest.json','Install.ps1','Launch.ps1','Uninstall.ps1','Uninstall.cmd','README.md')) {
        if (-not $listed.ContainsKey([IO.Path]::GetFullPath((Join-Path $PSScriptRoot $required)))) { throw "Incomplete package: $required" }
    }
    foreach ($entry in (Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -Force)) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package must not contain links.' }
        if (-not $entry.PSIsContainer -and $entry.FullName -ne (Join-Path $PSScriptRoot 'payload.json') -and -not $listed.ContainsKey($entry.FullName)) { throw "Unlisted package file: $($entry.Name)" }
    }
    $manifest = Get-Content (Join-Path $PSScriptRoot 'extension/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $hash = [Security.Cryptography.SHA256]::Create().ComputeHash([Convert]::FromBase64String($manifest.key))
    $id = -join ($hash[0..15] | ForEach-Object { [char](97 + ($_ -shr 4)); [char](97 + ($_ -band 15)) })
    if ($id -ne 'hooimhadihhgfkhidbmjoaojfljafnaf') { throw 'Extension identity mismatch' }
    return $manifest
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'payload.json'))) {
        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'Bootstrap.ps1')) {
            & (Join-Path $PSScriptRoot 'Bootstrap.ps1') -VerifyOnly:$VerifyOnly
            return
        }
        throw 'Incomplete installation package. Extract the whole ZIP or download the repository again.'
    }
    $manifest = Test-Package
    if ($VerifyOnly) { Write-Host 'Package verified; no system changes made.'; return }
    $base = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Chrome VPN for CottonClub'
    if ((Test-Path $base) -and ((Get-Item $base).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Installation directory must not be a link.' }
    if ((Test-Path $base) -and (Get-ChildItem $base -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) { throw 'Installation contents must not contain links.' }
    foreach ($process in @(Get-Process CottonClub-Host -ErrorAction SilentlyContinue)) {
        if ($process.Path -and $process.Path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Disable Chrome VPN for CottonClub in chrome://extensions before updating, then run Install.cmd again.' }
    }
    $release = Join-Path $base ('releases/' + [guid]::NewGuid().ToString('N'))
    # Unique releases avoid overwriting helper binaries during updates.
    New-Item -ItemType Directory -Path $release -Force | Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'host') $release -Recurse
    # Preserve the unpacked extension path across updates.
    Copy-Item (Join-Path $PSScriptRoot 'extension') $base -Recurse -Force
    foreach ($file in @('Launch.ps1','Uninstall.cmd','Uninstall.ps1','Bootstrap.ps1','Update.ps1','README.md')) { Copy-Item (Join-Path $PSScriptRoot $file) $base -Force }
    $id = 'hooimhadihhgfkhidbmjoaojfljafnaf'
    $hostPath = Join-Path $release 'com.cottonclub.hysteria2.json'
    $hostJson = @{name='com.cottonclub.hysteria2'; description='Chrome VPN for CottonClub'; path=(Join-Path $release 'host/CottonClub-Host.exe'); type='stdio'; allowed_origins=@("chrome-extension://$id/")} | ConvertTo-Json
    [IO.File]::WriteAllText($hostPath, $hostJson, [Text.UTF8Encoding]::new($false))
    $hkcu = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $key = $hkcu.CreateSubKey('Software\Google\Chrome\NativeMessagingHosts\com.cottonclub.hysteria2')
        try { $key.SetValue('', $hostPath) } finally { $key.Close() }
        $uninstall = $hkcu.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\CottonClubHysteria2')
        try {
            $uninstall.SetValue('DisplayName', 'Chrome VPN for CottonClub (Hysteria 2, current user)')
            $uninstall.SetValue('DisplayVersion', $manifest.version)
            $uninstall.SetValue('InstallLocation', $base)
            $uninstall.SetValue('UninstallString', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $base 'Uninstall.ps1') + '"')
        } finally { $uninstall.Close() }
    } finally { $hkcu.Close() }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))) {
        $shortcut = $shell.CreateShortcut((Join-Path $folder 'CottonClub Hysteria 2.lnk'))
        $shortcut.TargetPath = Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $base 'Launch.ps1') + '"'
        $shortcut.WindowStyle = 7
        $shortcut.WorkingDirectory = $base
        $shortcut.Save()
    }
    Add-Type -AssemblyName System.Windows.Forms
    $message = "Installed for your Windows account, without administrator rights. In chrome://extensions enable Developer mode, click Load unpacked and select:`n$base\extension`nOn update, reload the existing extension."
    [Windows.Forms.MessageBox]::Show($message, 'Chrome VPN for CottonClub') | Out-Null
} catch {
    if ($VerifyOnly) { throw }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Chrome VPN for CottonClub installation failed') | Out-Null
    throw
}

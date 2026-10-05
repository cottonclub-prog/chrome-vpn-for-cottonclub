$ErrorActionPreference = 'Stop'
try {
    $parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData')).TrimEnd('\')
    $base = [IO.Path]::GetFullPath((Join-Path $parent 'cottonclub vpn for chrome'))
    if ([IO.Path]::GetDirectoryName($base) -ne $parent -or [IO.Path]::GetFileName($base) -ne 'cottonclub vpn for chrome') { throw 'Invalid uninstall target' }
    if (-not (Test-Path $base)) { return }
    if ((Get-Item $base).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing linked installation directory' }
    if (Get-ChildItem $base -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Refusing linked installation contents' }
    foreach ($process in @(Get-Process chrome,cottonclub-vpn-for-chrome-host -ErrorAction SilentlyContinue)) {
        if ($process.Path -and $process.Path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Disconnect VPN and close cottonclub vpn for chrome browser windows before uninstalling.' }
    }
    $hkcu = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $registryPath = 'Software\Google\Chrome\NativeMessagingHosts\com.cottonclub.hysteria2'
        $key = $hkcu.OpenSubKey($registryPath)
        if ($key) {
            try { $value = [string]$key.GetValue('') } finally { $key.Close() }
            if (-not $value.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Another helper is registered; uninstall cancelled.' }
            $hkcu.DeleteSubKey($registryPath, $false)
        }
        $hkcu.DeleteSubKeyTree('Software\Microsoft\Windows\CurrentVersion\Uninstall\CottonClubVpnForChrome', $false)
    } finally { $hkcu.Close() }
    foreach ($folder in @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))) {
        $link = Join-Path $folder 'cottonclub vpn for chrome.lnk'
        if (Test-Path $link) { Remove-Item -LiteralPath $link }
    }
    Set-Location $parent
    # Preserve the device identity in the same directory for later reinstalls.
    foreach ($entry in @(Get-ChildItem -LiteralPath $base -Force)) {
        if ($entry.Name -ne 'device-id.txt') { Remove-Item -LiteralPath $entry.FullName -Recurse -Force }
    }
    if (-not (Get-ChildItem -LiteralPath $base -Force)) { Remove-Item -LiteralPath $base }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('Helper uninstalled. Remove cottonclub vpn for chrome in chrome://extensions. Device identity and user data are preserved.', 'cottonclub vpn for chrome') | Out-Null
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'cottonclub vpn for chrome uninstall failed') | Out-Null
    exit 1
}

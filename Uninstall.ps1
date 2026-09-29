$ErrorActionPreference = 'Stop'
try {
    $parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData')).TrimEnd('\')
    $base = [IO.Path]::GetFullPath((Join-Path $parent 'Chrome VPN for CottonClub'))
    if ([IO.Path]::GetDirectoryName($base) -ne $parent -or [IO.Path]::GetFileName($base) -ne 'Chrome VPN for CottonClub') { throw 'Invalid uninstall target' }
    if (-not (Test-Path $base)) { return }
    if ((Get-Item $base).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing linked installation directory' }
    if (Get-ChildItem $base -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Refusing linked installation contents' }
    foreach ($process in @(Get-Process chrome,CottonClub-Host -ErrorAction SilentlyContinue)) {
        if ($process.Path -and $process.Path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Disconnect VPN and close Chrome VPN for CottonClub browser windows before uninstalling.' }
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
        $hkcu.DeleteSubKeyTree('Software\Microsoft\Windows\CurrentVersion\Uninstall\CottonClubHysteria2', $false)
    } finally { $hkcu.Close() }
    foreach ($folder in @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))) {
        $link = Join-Path $folder 'CottonClub Hysteria 2.lnk'
        if (Test-Path $link) { Remove-Item -LiteralPath $link }
    }
    Set-Location $parent
    Remove-Item -LiteralPath $base -Recurse -Force
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('Helper uninstalled. Remove Chrome VPN for CottonClub in chrome://extensions. Device identity and user data are preserved.', 'Chrome VPN for CottonClub') | Out-Null
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Chrome VPN for CottonClub uninstall failed') | Out-Null
    exit 1
}

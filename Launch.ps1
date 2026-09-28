$ErrorActionPreference = 'Stop'
try {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) { throw 'Open the desktop shortcut from your normal Windows session, without Run as administrator.' }
        $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $chrome) { throw 'Google Chrome is not installed. Install Google Chrome and open this shortcut again.' }
        Start-Process -FilePath $chrome -ArgumentList 'chrome://extensions'
        Start-Process explorer.exe -ArgumentList ('"' + (Join-Path $PSScriptRoot 'extension') + '"')
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Chrome VPN for CottonClub') | Out-Null
    exit 1
}

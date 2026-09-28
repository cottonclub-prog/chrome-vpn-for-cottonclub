param([int]$WaitForHostPid = 0)
$ErrorActionPreference = 'Stop'
try {
    if ($WaitForHostPid -gt 0 -and (Get-Process -Id $WaitForHostPid -ErrorAction SilentlyContinue)) {
        Wait-Process -Id $WaitForHostPid -Timeout 30 -ErrorAction SilentlyContinue
        if (Get-Process -Id $WaitForHostPid -ErrorAction SilentlyContinue) { throw 'The VPN helper has not exited. Close the extension and retry.' }
    }
    & (Join-Path $PSScriptRoot 'Bootstrap.ps1') -Latest
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('Update finished. Open CottonClub and click Reload extension. If no new version was available, the current version was kept.', 'CottonClub update') | Out-Null
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('Update failed: ' + $_.Exception.Message + "`nOpen CottonClub and click Reload extension to resume using VPN.", 'CottonClub update') | Out-Null
    exit 1
}

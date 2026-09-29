param([int]$WaitForHostPid = 0, [ValidatePattern('^[a-f0-9]{32}$')][string]$UpdateId = ([guid]::NewGuid().ToString('N')))
$ErrorActionPreference = 'Stop'
function Set-UpdateStatus([string]$Phase, [string]$Version = '', [string]$Message = '') {
    $path = Join-Path $PSScriptRoot 'extension/update-status.json'
    $temporary = $path + '.' + $UpdateId + '.tmp'
    $json = @{id=$UpdateId; phase=$Phase; version=$Version; message=$Message} | ConvertTo-Json
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $path -Force
}
try {
    Set-UpdateStatus 'waiting'
    if ($WaitForHostPid -gt 0 -and (Get-Process -Id $WaitForHostPid -ErrorAction SilentlyContinue)) {
        Wait-Process -Id $WaitForHostPid -Timeout 30 -ErrorAction SilentlyContinue
        if (Get-Process -Id $WaitForHostPid -ErrorAction SilentlyContinue) { throw 'The VPN helper has not exited. Close the extension and retry.' }
    }
    Set-UpdateStatus 'installing'
    & (Join-Path $PSScriptRoot 'Bootstrap.ps1') -Latest -Quiet
    $installed = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'extension/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Set-UpdateStatus 'complete' $installed.version
} catch {
    Write-Output ('Update failed: ' + $_.Exception.Message)
    Set-UpdateStatus 'failed' '' $_.Exception.Message
    exit 1
}

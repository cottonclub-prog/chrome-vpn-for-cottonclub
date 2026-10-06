$ErrorActionPreference = 'Stop'

function Open-ChromeExtensionsWindow {
    param([string]$Chrome, [string[]]$AdditionalArguments = @())
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    if (-not ('CottonClubChromeWindow' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class CottonClubChromeWindow {
    private delegate bool Callback(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumWindows(Callback callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr window, uint message, IntPtr key, IntPtr data);
    public static IntPtr[] Find(string executable) {
        var result = new List<IntPtr>();
        EnumWindows((window, parameter) => {
            var name = new StringBuilder(256);
            GetClassName(window, name, name.Capacity);
            if (!IsWindowVisible(window) || name.ToString() != "Chrome_WidgetWin_1") return true;
            uint id; GetWindowThreadProcessId(window, out id);
            try {
                using (var process = Process.GetProcessById((int)id)) {
                    if (String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) result.Add(window);
                }
            } catch (System.ComponentModel.Win32Exception) {} catch (InvalidOperationException) {} catch (ArgumentException) {}
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }
    public static void Enter(IntPtr window) {
        // Send only to the verified Chrome window, never to the foreground application.
        PostMessage(window, 0x0100, new IntPtr(13), new IntPtr(1));
        PostMessage(window, 0x0101, new IntPtr(13), new IntPtr(unchecked((int)0xC0000001)));
    }
}
'@
    }
    $previous = @([CottonClubChromeWindow]::Find($Chrome))
    # Chrome filters internal URLs supplied on the command line. Open a blank window first.
    Start-Process -FilePath $Chrome -ArgumentList (@('--new-window', 'about:blank') + $AdditionalArguments) -WindowStyle Normal
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        foreach ($handle in [CottonClubChromeWindow]::Find($Chrome)) {
            if ($previous -contains $handle) { continue }
            try {
                $window = [Windows.Automation.AutomationElement]::FromHandle($handle)
                $condition = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty, [Windows.Automation.ControlType]::Edit)
                $fields = $window.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)
                foreach ($field in $fields) {
                    $pattern = $null
                    if (-not $field.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) { continue }
                    if ($pattern.Current.Value -ne 'about:blank') { continue }
                    $pattern.SetValue('chrome://extensions/')
                    $field.SetFocus()
                    [CottonClubChromeWindow]::Enter($handle)
                    return
                }
            } catch [Windows.Automation.ElementNotAvailableException] { }
        }
        Start-Sleep -Milliseconds 200
    }
    throw 'Could not open the Chrome extensions page automatically. Open chrome://extensions manually.'
}

try {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) { throw 'Open the desktop shortcut from your normal Windows session, without Run as administrator.' }
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $chrome) { throw 'Google Chrome is not installed. Install Google Chrome and open this shortcut again.' }
    Open-ChromeExtensionsWindow -Chrome $chrome
    Start-Process explorer.exe -ArgumentList ('"' + (Join-Path $PSScriptRoot 'CottonClub VPN for Chrome') + '"') -WindowStyle Normal
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'CottonClub VPN for Chrome') | Out-Null
    exit 1
}

param([switch]$SelfTest, [string]$InstallDirectory)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# This utility does not install anything, change Chrome or query a subscription.
# Raw process output and the connection URL are never included in its report.
$diagnosticCode = @'
using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Threading;
using System.Net;
using System.Net.Sockets;
using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace CottonClubDiagnostic {
    public class Native : IDisposable {
        Process process;
        FileSystemWatcher watcher;
        readonly object gate = new object();
        string captured;
        public Native(string executable, string origin, string isolatedParent) {
            string folder = Path.Combine(isolatedParent, "CottonClub VPN for Chrome");
            Directory.CreateDirectory(folder);
            watcher = new FileSystemWatcher(folder, "core-*.json");
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
            watcher.Created += Capture; watcher.Changed += Capture;
            watcher.EnableRaisingEvents = true;
            process = new Process();
            process.StartInfo = new ProcessStartInfo(executable, origin);
            process.StartInfo.UseShellExecute = false;
            process.StartInfo.CreateNoWindow = true;
            process.StartInfo.RedirectStandardInput = true;
            process.StartInfo.RedirectStandardOutput = true;
            process.StartInfo.RedirectStandardError = true;
            process.StartInfo.EnvironmentVariables["LOCALAPPDATA"] = isolatedParent;
            process.StartInfo.EnvironmentVariables["TEMP"] = isolatedParent;
            process.StartInfo.EnvironmentVariables["TMP"] = isolatedParent;
            process.ErrorDataReceived += delegate { /* intentionally discard */ };
            process.Start(); process.BeginErrorReadLine();
        }
        void Capture(object sender, FileSystemEventArgs e) {
            try {
                string text = File.ReadAllText(e.FullPath, Encoding.UTF8);
                if (text.Length > 2 * 1024 * 1024) return;
                var value = new JavaScriptSerializer().DeserializeObject(text) as Dictionary<string, object>;
                if (value == null || !value.ContainsKey("outbounds") || !value.ContainsKey("inbounds")) return;
                lock (gate) { captured = text; }
            } catch { /* A write may still be in progress; the next change retries. */ }
        }
        public string Config { get { lock (gate) { return captured; } } }
        public void Send(string text) {
            byte[] body = Encoding.UTF8.GetBytes(text);
            if (body.Length > 2 * 1024 * 1024) throw new InvalidDataException();
            byte[] header = BitConverter.GetBytes(body.Length);
            Stream stream = process.StandardInput.BaseStream;
            stream.Write(header, 0, 4); stream.Write(body, 0, body.Length); stream.Flush();
        }
        static byte[] Exact(Stream stream, int size) {
            byte[] result = new byte[size]; int offset = 0;
            while (offset < size) {
                int n = stream.Read(result, offset, size - offset);
                if (n == 0) throw new EndOfStreamException();
                offset += n;
            }
            return result;
        }
        public string Receive(int milliseconds) {
            var task = Task.Factory.StartNew(delegate {
                Stream stream = process.StandardOutput.BaseStream;
                int size = BitConverter.ToInt32(Exact(stream, 4), 0);
                if (size <= 0 || size > 2 * 1024 * 1024) throw new InvalidDataException();
                return Encoding.UTF8.GetString(Exact(stream, size));
            });
            if (!task.Wait(milliseconds)) { Dispose(); throw new TimeoutException(); }
            return task.Result;
        }
        public void Dispose() {
            if (watcher != null) { watcher.Dispose(); watcher = null; }
            if (process != null) {
                try { process.StandardInput.Close(); if (!process.WaitForExit(5000)) { process.Kill(); process.WaitForExit(5000); } } catch { }
                process.Dispose(); process = null;
            }
            lock (gate) { captured = null; }
        }
    }
    public class Core : IDisposable {
        Process process;
        readonly object gate = new object();
        readonly HashSet<string> categories = new HashSet<string>();
        int port;
        public Core(string executable, string config, string directory) {
            process = new Process();
            process.StartInfo = new ProcessStartInfo(executable, "run -c \"" + config + "\"");
            process.StartInfo.WorkingDirectory = directory;
            process.StartInfo.UseShellExecute = false; process.StartInfo.CreateNoWindow = true;
            process.StartInfo.RedirectStandardOutput = true; process.StartInfo.RedirectStandardError = true;
            process.OutputDataReceived += Log; process.ErrorDataReceived += Log;
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
        }
        public static string Category(string raw) {
            string line = (raw ?? "").ToLowerInvariant();
            if (line.Contains("handshake failure") || line.Contains("handshake_failure") || line.Contains("crypto_error")) return "QUIC_TLS_HANDSHAKE";
            if (line.Contains("x509:") || (line.Contains("certificate") && (line.Contains("failed") || line.Contains("invalid") || line.Contains("expired") || line.Contains("unknown") || line.Contains("mismatch")))) return "SERVER_CERTIFICATE";
            if (line.Contains("authentication failed") || line.Contains("authentication error") || line.Contains("auth failed") || line.Contains("unauthorized")) return "HYSTERIA_AUTHENTICATION";
            if (line.Contains("no such host") || line.Contains("failed to lookup") || line.Contains("dns lookup failed")) return "DNS_LOOKUP";
            if (line.Contains("access permissions") || line.Contains("permission denied") || line.Contains("access is denied")) return "OS_NETWORK_PERMISSION";
            if (line.Contains("i/o timeout") || line.Contains("context deadline exceeded") || line.Contains("connection timed out") || line.Contains("no recent network activity")) return "NETWORK_TIMEOUT";
            if (line.Contains("connection refused") || line.Contains("actively refused")) return "CONNECTION_REFUSED";
            if (line.Contains("network is unreachable") || line.Contains("no route to host")) return "NETWORK_UNREACHABLE";
            return null;
        }
        public static string NativeCategory(string error) {
            string text = error ?? "";
            foreach (string stage in new[] { "LOCAL_PROXY", "SOCKS_GREETING", "SOCKS_CONNECT", "HTTPS_TLS", "HTTP_HEADERS", "HTTP_BODY" }) {
                foreach (string outcome in new[] { "TIMEOUT", "CLOSED", "REFUSED" }) {
                    string code = stage + "_" + outcome;
                    if (text.Contains("[" + code + "]")) return code;
                }
            }
            foreach (string code in new[] { "HTTPS_CERTIFICATE", "HTTPS_TLS_ERROR", "HTTP_STATUS", "HTTP_INVALID_IP", "HTTP_INCOMPLETE", "SOCKS_REPLY_INVALID", "SOCKS_GREETING_INVALID", "LOCAL_PROXY_PORT", "OS_NETWORK_PERMISSION" }) {
                if (text.Contains("[" + code + "]")) return code;
            }
            for (int reply = 1; reply <= 255; reply++) {
                string code = "SOCKS_REPLY_" + reply;
                if (text.Contains("[" + code + "]")) return code;
            }
            if (text.Contains("\u0418\u0441\u0442\u0435\u043a\u043b\u043e \u0432\u0440\u0435\u043c\u044f \u043e\u0436\u0438\u0434\u0430\u043d\u0438\u044f")) return "HTTPS_TIMEOUT";
            if (text.Contains("TLS-\u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442")) return "HTTPS_CERTIFICATE";
            if (text.Contains("\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0440\u043e\u043a\u0441\u0438")) return "LOCAL_PROXY_START";
            if (text.Contains("\u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446")) return "CONFIG_REJECTED";
            return "OTHER_ERROR";
        }
        void Log(object sender, DataReceivedEventArgs e) {
            if (e.Data == null || e.Data.Length > 8192) return;
            string plain = Regex.Replace(e.Data, "\u001b\\[[0-9;]*m", "");
            Match match = Regex.Match(plain, @"inbound/mixed\[browser\]: tcp server started at 127\.0\.0\.1:([0-9]{1,5})\s*$");
            string category = Category(plain);
            lock (gate) {
                int found;
                if (match.Success && Int32.TryParse(match.Groups[1].Value, out found) && found > 0 && found <= 65535 && port == 0) port = found;
                if (category != null) categories.Add(category);
            }
        }
        public int Port { get { lock (gate) { return port; } } }
        public string[] Categories { get { lock (gate) { var result = new string[categories.Count]; categories.CopyTo(result); Array.Sort(result); return result; } } }
        public bool Alive { get { return process != null && !process.HasExited; } }
        public void Dispose() {
            if (process != null) {
                try { if (!process.HasExited) { process.Kill(); process.WaitForExit(5000); } } catch { }
                process.Dispose(); process = null;
            }
        }
    }
    public class Result {
        public string Phase;
        public string Outcome;
        public int SocksReply = -1;
        public int HttpStatus;
        public int ElapsedMs;
        public int SocksConnectMs = -1;
    }
    public static class Probe {
        static byte[] Read(Stream stream, int length, Stopwatch watch) {
            byte[] bytes = new byte[length]; int count = 0;
            while (count < length) {
                int remaining = 90000 - (int)watch.ElapsedMilliseconds;
                if (remaining <= 0) throw new TimeoutException();
                stream.ReadTimeout = Math.Min(stream.ReadTimeout, remaining);
                int n = stream.Read(bytes, count, length - count);
                if (n == 0) throw new EndOfStreamException();
                count += n;
            }
            return bytes;
        }
        public static Result Https(int port, string domain, string path, bool expectIp) {
            var result = new Result { Phase = "LOCAL_TCP", Outcome = "FAILED" };
            var watch = Stopwatch.StartNew();
            using (var socket = new TcpClient())
            using (var watchdog = new Timer(delegate { try { socket.Close(); } catch { } }, null, 90000, Timeout.Infinite)) {
                try {
                    var connect = socket.ConnectAsync(IPAddress.Loopback, port);
                    if (!connect.Wait(8000)) throw new TimeoutException();
                    connect.GetAwaiter().GetResult();
                    NetworkStream stream = socket.GetStream(); stream.ReadTimeout = 8000; stream.WriteTimeout = 8000;
                    result.Phase = "SOCKS_GREETING";
                    stream.Write(new byte[] { 5, 1, 0 }, 0, 3);
                    byte[] hello = Read(stream, 2, watch);
                    if (hello[0] != 5 || hello[1] != 0) { result.Outcome = "INVALID_REPLY"; return result; }
                    result.Phase = "SOCKS_CONNECT";
                    int socksStarted = (int)watch.ElapsedMilliseconds;
                    stream.ReadTimeout = 35000;
                    byte[] name = Encoding.ASCII.GetBytes(domain);
                    byte[] request = new byte[7 + name.Length];
                    request[0] = 5; request[1] = 1; request[3] = 3; request[4] = (byte)name.Length;
                    Buffer.BlockCopy(name, 0, request, 5, name.Length); request[request.Length - 2] = 1; request[request.Length - 1] = 187;
                    stream.Write(request, 0, request.Length);
                    byte[] reply = Read(stream, 4, watch); result.SocksReply = reply[1];
                    result.SocksConnectMs = (int)watch.ElapsedMilliseconds - socksStarted;
                    if (reply[0] != 5 || reply[2] != 0) { result.Outcome = "INVALID_REPLY"; return result; }
                    if (reply[1] != 0) { result.Outcome = "REJECTED"; return result; }
                    if (reply[3] == 1) Read(stream, 6, watch);
                    else if (reply[3] == 4) Read(stream, 18, watch);
                    else if (reply[3] == 3) { int n = Read(stream, 1, watch)[0]; Read(stream, n + 2, watch); }
                    else { result.Outcome = "INVALID_REPLY"; return result; }
                    result.Phase = "HTTPS_TLS";
                    stream.ReadTimeout = 8000;
                    SslPolicyErrors validation = SslPolicyErrors.None;
                    using (var tls = new SslStream(stream, false, delegate(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) { validation = errors; return errors == SslPolicyErrors.None; })) {
                        var auth = tls.BeginAuthenticateAsClient(domain, new X509CertificateCollection(), SslProtocols.Tls12, false, null, null);
                        if (!auth.AsyncWaitHandle.WaitOne(8000)) throw new TimeoutException();
                        try { tls.EndAuthenticateAsClient(auth); }
                        catch (AuthenticationException) { result.Outcome = validation != SslPolicyErrors.None ? "CERTIFICATE_FAILED" : "TLS_FAILED"; return result; }
                        result.Phase = "HTTPS_RESPONSE";
                        tls.ReadTimeout = 15000; tls.WriteTimeout = 8000;
                        byte[] http = Encoding.ASCII.GetBytes("GET " + path + " HTTP/1.0\r\nHost: " + domain + "\r\nConnection: close\r\nUser-Agent: CottonClub-Diagnostic\r\n\r\n");
                        tls.Write(http, 0, http.Length); tls.Flush();
                        using (var output = new MemoryStream()) {
                            byte[] buffer = new byte[1024];
                            while (output.Length < 16384) {
                                int remaining = 90000 - (int)watch.ElapsedMilliseconds;
                                if (remaining <= 0) throw new TimeoutException();
                                tls.ReadTimeout = Math.Min(15000, remaining);
                                int n = tls.Read(buffer, 0, Math.Min(buffer.Length, 16384 - (int)output.Length));
                                if (n == 0) break;
                                output.Write(buffer, 0, n);
                            }
                            string response = Encoding.UTF8.GetString(output.ToArray());
                            Match status = Regex.Match(response, @"\AHTTP/1\.[01] ([0-9]{3})");
                            if (!status.Success) { result.Outcome = "INVALID_HTTP"; return result; }
                            result.HttpStatus = Int32.Parse(status.Groups[1].Value);
                            if (result.HttpStatus != 200) { result.Outcome = "HTTP_ERROR"; return result; }
                            if (expectIp) {
                                int split = response.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                                IPAddress ip;
                                if (split < 0 || !IPAddress.TryParse(response.Substring(split + 4).Trim(), out ip)) { result.Outcome = "INVALID_IP_RESPONSE"; return result; }
                            }
                            result.Phase = "COMPLETE"; result.Outcome = "OK"; return result;
                        }
                    }
                } catch (TimeoutException) { result.Outcome = "TIMEOUT"; }
                  catch (SocketException error) { result.Outcome = error.SocketErrorCode == SocketError.TimedOut ? "TIMEOUT" : "SOCKET_FAILED"; }
                  catch (IOException error) { var socketError = error.InnerException as SocketException; result.Outcome = socketError != null && socketError.SocketErrorCode == SocketError.TimedOut ? "TIMEOUT" : "IO_FAILED"; }
                  catch (AuthenticationException) { result.Outcome = "TLS_FAILED"; }
                  catch { result.Outcome = "FAILED"; }
                  finally { result.ElapsedMs = (int)watch.ElapsedMilliseconds; }
            }
            return result;
        }
    }
}
'@

function Initialize-DiagnosticTypes {
    if (-not ('CottonClubDiagnostic.Native' -as [type])) {
        Add-Type -TypeDefinition $diagnosticCode -ReferencedAssemblies System.Web.Extensions.dll
    }
}

function Get-DiagnosticHost([string]$Directory) {
    $origin = 'chrome-extension://hooimhadihhgfkhidbmjoaojfljafnaf/'
    $parent = [Environment]::GetFolderPath('LocalApplicationData')
    $base = Join-Path $parent 'CottonClub VPN for Chrome'
    if ($Directory) {
        $base = [IO.Path]::GetFullPath($Directory)
        $hostPath = Join-Path $base 'host\cottonclub-vpn-for-chrome-host.exe'
    } else {
        $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
        try {
        $key = $registry.OpenSubKey('Software\Google\Chrome\NativeMessagingHosts\com.cottonclub.hysteria2', $false)
        if ($key) {
            try { $manifestPath = [string]$key.GetValue('') } finally { $key.Close() }
            if ($manifestPath -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
                $manifest = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
                if ($manifest.name -eq 'com.cottonclub.hysteria2' -and $manifest.allowed_origins -contains $origin) {
                    $hostPath = [string]$manifest.path
                }
            }
        }
        } finally { $registry.Close() }
    }
    # A stale registry path must not hide the helper present in the current
    # user's standard installation folder.
    if (-not $hostPath -or -not (Test-Path -LiteralPath $hostPath -PathType Leaf)) {
        $hostPath = Join-Path $base 'host\cottonclub-vpn-for-chrome-host.exe'
    }
    if (-not (Test-Path -LiteralPath $hostPath -PathType Leaf)) { throw 'HOST_NOT_FOUND' }
    $hostPath = [IO.Path]::GetFullPath($hostPath)
    if ([IO.Path]::GetFileName($hostPath) -cne 'cottonclub-vpn-for-chrome-host.exe') { throw 'HOST_NOT_RECOGNIZED' }
    $hostDirectory = [IO.Path]::GetDirectoryName($hostPath)
    $base = [IO.Path]::GetDirectoryName($hostDirectory)
    $binary = Join-Path $hostDirectory 'bin\sing-box.exe'
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'CORE_NOT_FOUND' }
    $version = 'unknown'
    $extensionManifest = Join-Path $base 'CottonClub VPN for Chrome\manifest.json'
    if (Test-Path -LiteralPath $extensionManifest -PathType Leaf) {
        $candidate = ([IO.File]::ReadAllText($extensionManifest) | ConvertFrom-Json).version
        if ($candidate -match '^\d+\.\d+\.\d+$') { $version = $candidate }
    }
    return @{ Helper = $hostPath; Binary = $binary; Origin = $origin; Version = $version }
}

function Write-ProbeResult([string]$Name, $Result) {
    $extra = ''
    if ($Result.SocksReply -ge 0) { $extra += '; socks=' + $Result.SocksReply }
    if ($Result.SocksConnectMs -ge 0) { $extra += '; socks_connect_ms=' + $Result.SocksConnectMs }
    if ($Result.HttpStatus) { $extra += '; http=' + $Result.HttpStatus }
    Write-Host ($Name + ': ' + $Result.Phase + '/' + $Result.Outcome + '; ms=' + $Result.ElapsedMs + $extra)
}

function Get-DiagnosticCoreVersion([string]$Binary) {
    $process = New-Object Diagnostics.Process
    $process.StartInfo = New-Object Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = $Binary
    $process.StartInfo.Arguments = 'version'
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        [void]$process.Start()
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(5000)) { $process.Kill(); [void]$process.WaitForExit(5000); return 'unknown' }
        if (-not $output.Wait(2000)) { return 'unknown' }
        $found = [regex]::Match($output.Result, '(?m)^sing-box version ([0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*))\s*$')
        if ($found.Success) { return $found.Groups[1].Value }
        return 'unknown'
    } finally { $process.Dispose() }
}

function Remove-DiagnosticDirectory([string]$Path, [string]$Parent) {
    $target = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $expectedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($target) -ine $expectedParent -or [IO.Path]::GetFileName($target) -notmatch '^CottonClubDiagnostic-[0-9a-f]{32}$') { throw 'UNSAFE_CLEANUP_PATH' }
    if (-not (Test-Path -LiteralPath $target)) { return }
    $entries = @((Get-Item -LiteralPath $target -Force)) + @(Get-ChildItem -LiteralPath $target -Recurse -Force)
    foreach ($entry in $entries) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'UNSAFE_CLEANUP_LINK' }
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

Initialize-DiagnosticTypes
if ($SelfTest) {
    $examples = @{
        'tls: handshake failure CRYPTO_ERROR 0x128' = 'QUIC_TLS_HANDSHAKE'
        'certificate unknown x509: secret-server.example' = 'SERVER_CERTIFICATE'
        'authentication failed password-secret' = 'HYSTERIA_AUTHENTICATION'
        'context deadline exceeded secret-server.example' = 'NETWORK_TIMEOUT'
        'no such host secret-server.example' = 'DNS_LOOKUP'
    }
    foreach ($example in $examples.GetEnumerator()) {
        if ([CottonClubDiagnostic.Core]::Category($example.Key) -ne $example.Value) { throw 'CLASSIFIER_SELF_TEST_FAILED' }
    }
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    $probe = [CottonClubDiagnostic.Probe]::Https($port, 'api.ipify.org', '/', $true)
    if ($probe.Phase -ne 'LOCAL_TCP' -or $probe.Outcome -eq 'OK') { throw 'PROBE_SELF_TEST_FAILED' }
    $refusedCleanup = $false
    try { Remove-DiagnosticDirectory $PSScriptRoot $PSScriptRoot }
    catch { $refusedCleanup = $_.Exception.Message -eq 'UNSAFE_CLEANUP_PATH' }
    if (-not $refusedCleanup) { throw 'CLEANUP_SELF_TEST_FAILED' }
    Write-Host 'Offline classifier, local connection refusal and unsafe cleanup refusal checks passed.'
    return
}

Write-Host 'CottonClub VPN diagnostic (no installation / no Chrome changes).'
Write-Host 'Disconnect VPN in the extension before this test. Leave other clients disconnected.'
Write-Host 'Paste the SAME hysteria2:// or hy2:// server link that works in the other client.'
Write-Host 'The link is hidden; subscription URLs are not accepted or downloaded.'
$native = $null
$core = $null
$secureLink = $null
$link = $null
$config = $null
$configurationText = $null
$tempDirectory = $null
$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
try {
    $installation = Get-DiagnosticHost $InstallDirectory
    Write-Host ('Extension version: ' + $installation.Version)
    Write-Host ('sing-box version: ' + (Get-DiagnosticCoreVersion $installation.Binary))
    Write-Host ('Windows version: ' + [Environment]::OSVersion.Version.ToString())
    $secureLink = Read-Host 'Server link' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureLink)
    try { $link = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($link.Length -gt 65536 -or $link -notmatch '^(hysteria2|hy2)://[^\r\n]+$') { throw 'EXPECTED_SINGLE_HYSTERIA2_LINK' }
    $tempDirectory = Join-Path $tempParent ('CottonClubDiagnostic-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
    $native = New-Object CottonClubDiagnostic.Native($installation.Helper, $installation.Origin, $tempDirectory)
    $native.Send((@{ id = 1; action = 'load'; subscription = $link } | ConvertTo-Json -Compress))
    $link = $null
    $loaded = $native.Receive(30000) | ConvertFrom-Json
    if (-not $loaded.ok) { throw 'INSTALLED_HELPER_REJECTED_LINK' }
    $loaded = $null
    Write-Host 'Link parsed by the installed helper: OK'
    $nativeWatch = [Diagnostics.Stopwatch]::StartNew()
    $native.Send('{"id":2,"action":"connect","index":0,"routing_mode":"all"}')
    $response = $native.Receive(60000) | ConvertFrom-Json
    $nativeWatch.Stop()
    if ($response.ok) { Write-Host ('Installed helper HTTPS check: OK; ms=' + $nativeWatch.ElapsedMilliseconds) }
    else {
        $reason = [CottonClubDiagnostic.Core]::NativeCategory($response.error)
        Write-Host ('Installed helper HTTPS check: ' + $reason + '; ms=' + $nativeWatch.ElapsedMilliseconds)
    }
    $response = $null
    $configurationText = $native.Config
    $native.Dispose(); $native = $null
    if (-not $configurationText) { throw 'TRANSIENT_CONFIG_NOT_CAPTURED_RETRY_TEST' }
    $config = $configurationText | ConvertFrom-Json
    $configurationText = $null
    if ($config.inbounds.Count -ne 1 -or $config.inbounds[0].tag -ne 'browser' -or $config.route.final -ne 'vpn') { throw 'UNEXPECTED_CONFIG' }
    $config.inbounds[0].listen = '127.0.0.1'
    $config.inbounds[0].listen_port = 0
    $config.log.level = 'debug'
    $outbound = @($config.outbounds | Where-Object tag -eq 'vpn')
    if ($outbound.Count -ne 1 -or $outbound[0].type -ne 'hysteria2') { throw 'UNEXPECTED_OUTBOUND' }
    $parrot = if ($outbound[0].PSObject.Properties['disable_chrome_parrot']) { [string][bool]$outbound[0].disable_chrome_parrot } else { 'default' }
    $obfs = if ($outbound[0].obfs) { 'enabled' } else { 'none' }
    $ports = if ($outbound[0].server_ports) { 'hopping' } else { 'single' }
    Write-Host ('Generated config: Hysteria2; obfs=' + $obfs + '; ports=' + $ports + '; chrome_parrot_disabled=' + $parrot)
    $configPath = Join-Path $tempDirectory 'diagnostic-core.json'
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 30 -Compress), (New-Object Text.UTF8Encoding($false)))
    $config = $null
    $core = New-Object CottonClubDiagnostic.Core($installation.Binary, $configPath, $tempDirectory)
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ($core.Alive -and -not $core.Port -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
    if (-not $core.Alive -or -not $core.Port) { throw 'DIAGNOSTIC_CORE_START_FAILED' }
    Remove-Item -LiteralPath $configPath -Force
    Write-Host 'Diagnostic core listener: OK (OS-assigned port)'
    Write-Host 'Diagnostic SOCKS CONNECT waits up to 35s; compare with the measured installed-helper time above.'
    $ipify = [CottonClubDiagnostic.Probe]::Https($core.Port, 'api.ipify.org', '/', $true)
    Write-ProbeResult 'ipify via same core' $ipify
    $alternate = [CottonClubDiagnostic.Probe]::Https($core.Port, 'www.cloudflare.com', '/cdn-cgi/trace', $false)
    Write-ProbeResult 'Cloudflare via same core' $alternate
    $categories = @($core.Categories)
    Write-Host ('Core categories: ' + $(if ($categories.Count) { $categories -join ', ' } else { 'NONE_RECORDED' }))
    if ($ipify.Outcome -eq 'OK' -and $alternate.Outcome -eq 'OK') {
        Write-Host 'Result: tunnel and both HTTPS endpoints work in this test.'
        Write-Host 'If the installed helper failed, compare its Python/certifi check with the Windows TLS probe; this report does not prove a root cause.'
    } elseif ($ipify.Phase -eq 'SOCKS_CONNECT' -and $ipify.Outcome -ne 'OK') {
        Write-Host 'Result: failure before HTTPS TLS. Hysteria/server-side connection or upstream connection failed.'
        Write-Host 'A timeout alone cannot distinguish UDP filtering, wrong obfuscation/password, server silence or upstream delay.'
    } elseif ($ipify.Outcome -ne 'OK' -and $alternate.Outcome -eq 'OK') {
        Write-Host 'Result: this tunnel works to Cloudflare; the ipify check fails. See its exact phase above.'
    } else {
        Write-Host 'Result: use the phase and fixed core categories above; no unique cause has been proven yet.'
    }
    Write-Host 'HTTPS diagnostic uses Windows certificate trust and TLS 1.2; the installed helper uses Python/certifi.'
} catch {
    $fixed = @('HOST_NOT_FOUND', 'HOST_NOT_RECOGNIZED', 'CORE_NOT_FOUND', 'EXPECTED_SINGLE_HYSTERIA2_LINK', 'INSTALLED_HELPER_REJECTED_LINK', 'TRANSIENT_CONFIG_NOT_CAPTURED_RETRY_TEST', 'UNEXPECTED_CONFIG', 'UNEXPECTED_OUTBOUND', 'DIAGNOSTIC_CORE_START_FAILED')
    $failure = 'DIAGNOSTIC_FAILED'
    if ($fixed -contains $_.Exception.Message) { $failure = $_.Exception.Message }
    elseif ($_.Exception.ToString() -match 'TimeoutException') { $failure = 'NATIVE_HELPER_TIMEOUT' }
    Write-Host ('Diagnostic result: ' + $failure)
    if ($core) { Write-Host ('Core categories: ' + ($core.Categories -join ', ')) }
} finally {
    if ($native) { $native.Dispose() }
    if ($core) { $core.Dispose() }
    if ($secureLink) { $secureLink.Dispose() }
    $link = $null; $configurationText = $null; $config = $null
    if ($tempDirectory) {
        try { Remove-DiagnosticDirectory $tempDirectory $tempParent }
        catch { Write-Host 'Temporary diagnostic cleanup failed; no secret contents were printed.' }
    }
}

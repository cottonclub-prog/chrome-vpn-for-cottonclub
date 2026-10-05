using System;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Diagnostics;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (Array.Exists(args, x => x == "--verify-only"))
        {
            try { Install(false, (p, text) => {}); return 0; }
            catch { return 1; }
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupForm());
        return 0;
    }

    internal static void Install(bool install, Action<int, string> progress)
    {
        if (install && new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            throw new InvalidOperationException("Запустите установщик обычным двойным щелчком, без прав администратора.");
        string tempRoot = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
        string work = Path.GetFullPath(Path.Combine(tempRoot, "CottonClubSetup-" + Guid.NewGuid().ToString("N")));
        if (!String.Equals(Path.GetDirectoryName(work), tempRoot, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Недопустимый временный путь.");
        Directory.CreateDirectory(work);
        try
        {
            progress(2, "Проверка установочного комплекта…");
            Assembly assembly = Assembly.GetExecutingAssembly();
            string expected;
            using (var reader = new StreamReader(assembly.GetManifestResourceStream("payload.sha256")))
                expected = reader.ReadToEnd().Trim();
            using (Stream payload = assembly.GetManifestResourceStream("payload.zip"))
            {
                using (SHA256 sha = SHA256.Create())
                {
                    string actual = BitConverter.ToString(sha.ComputeHash(payload)).Replace("-", "").ToLowerInvariant();
                    if (actual != expected) throw new InvalidDataException("Установочный комплект повреждён.");
                }
                payload.Position = 0;
                using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
                {
                    long total = 0, copied = 0;
                    foreach (var entry in archive.Entries) total += entry.Length;
                    progress(10, "Распаковка файлов…");
                    foreach (var entry in archive.Entries)
                    {
                        string target = Path.GetFullPath(Path.Combine(work, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                        if (!target.StartsWith(work + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidDataException("Недопустимый путь в архиве.");
                        if (String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(target); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        using (var input = entry.Open())
                        using (var output = new FileStream(target, FileMode.CreateNew))
                        {
                            byte[] buffer = new byte[131072]; int count;
                            while ((count = input.Read(buffer, 0, buffer.Length)) > 0)
                            {
                                output.Write(buffer, 0, count); copied += count;
                                progress(10 + (int)(copied * 55 / Math.Max(total, 1)), "Распаковка файлов…");
                            }
                        }
                    }
                }
            }
            string package = Path.Combine(work, "Chrome-vpn-for-cottonclub");
            progress(70, "Проверка контрольных сумм файлов…");
            RunInstaller(package, true);
            if (install)
            {
                progress(85, "Установка помощника, ядра и расширения…");
                RunInstaller(package, false);
            }
            progress(100, install ? "Установка завершена" : "Комплект проверен");
        }
        finally
        {
            // Only the uniquely created workspace can be removed.
            if (Directory.Exists(work) && String.Equals(Path.GetDirectoryName(work), tempRoot, StringComparison.OrdinalIgnoreCase))
            {
                try { Directory.Delete(work, true); } catch (IOException) {} catch (UnauthorizedAccessException) {}
            }
        }
    }

    private static void RunInstaller(string package, bool verify)
    {
        string executable = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        var info = new ProcessStartInfo(executable, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"" + Path.Combine(package, "Install.ps1") + "\" " + (verify ? "-VerifyOnly" : "-Quiet"));
        info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        using (var process = Process.Start(info))
        {
            Task<string> output = process.StandardOutput.ReadToEndAsync();
            Task<string> error = process.StandardError.ReadToEndAsync();
            process.WaitForExit(); Task.WaitAll(output, error);
            if (process.ExitCode != 0)
                throw new InvalidOperationException("Установка не завершена. Отключите VPN и выключите расширение в chrome://extensions, затем повторите установку.\r\n\r\n" + error.Result);
        }
    }
}

internal sealed class SetupForm : Form
{
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Label status = new Label();
    private readonly Button action = new Button();
    private readonly CheckBox openChrome = new CheckBox();
    private readonly BackgroundWorker worker = new BackgroundWorker();
    private bool installed;

    internal SetupForm()
    {
        Text = "COTTONCLUB VPN — установка"; ClientSize = new Size(540, 370);
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(36, 35, 35); ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var heading = new Label { Text = "COTTONCLUB VPN", Font = new Font("Segoe UI", 20, FontStyle.Bold), Location = new Point(30, 25), AutoSize = true };
        var description = new Label { Text = "Hysteria 2 · sing-box\r\nУстановка для текущего пользователя без прав администратора.", Location = new Point(32, 80), Size = new Size(475, 55), ForeColor = Color.LightGray };
        status.Text = "Перед обновлением отключите VPN и выключите расширение в Chrome.";
        status.Location = new Point(32, 150); status.Size = new Size(475, 64);
        progress.Location = new Point(32, 220); progress.Size = new Size(475, 16);
        progress.Style = ProgressBarStyle.Continuous;
        openChrome.Text = "Открыть Chrome и папку расширения после установки";
        openChrome.Location = new Point(32, 250); openChrome.Size = new Size(475, 32); openChrome.Checked = true;
        action.Text = "Установить"; action.Location = new Point(340, 305); action.Size = new Size(167, 40);
        action.FlatStyle = FlatStyle.Flat; action.BackColor = Color.FromArgb(0, 141, 221); action.FlatAppearance.BorderSize = 0;
        Controls.AddRange(new Control[] { heading, description, status, progress, openChrome, action });
        worker.WorkerReportsProgress = true;
        worker.DoWork += (s, e) => Program.Install(true, (p, text) => worker.ReportProgress(p, text));
        worker.ProgressChanged += (s, e) => { progress.Value = e.ProgressPercentage; status.Text = (string)e.UserState; };
        worker.RunWorkerCompleted += (s, e) => {
            action.Enabled = true;
            if (e.Error != null) { status.Text = "Установка не завершена. Можно повторить попытку."; MessageBox.Show(this, e.Error.Message, "COTTONCLUB VPN", MessageBoxButtons.OK, MessageBoxIcon.Error); return; }
            installed = true; action.Text = "Закрыть";
            status.Text = "Готово. В chrome://extensions загрузите установленную папку или перезагрузите существующее расширение. CRX устанавливается через корпоративную политику.";
        };
        action.Click += (s, e) => {
            if (!installed) { action.Enabled = false; worker.RunWorkerAsync(); return; }
            if (openChrome.Checked) {
                string script = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Chrome VPN for CottonClub", "Launch.ps1");
                var info = new ProcessStartInfo("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"") { UseShellExecute = false, CreateNoWindow = true };
                Process.Start(info);
            }
            Close();
        };
        FormClosing += (s, e) => { if (worker.IsBusy) e.Cancel = true; };
    }
}

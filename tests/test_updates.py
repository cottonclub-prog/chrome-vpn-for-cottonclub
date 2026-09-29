import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from native_host import Host
from updates import ASSET, REPOSITORY, parse_release, launch_update


def release(version='1.0.4'):
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'assets': [{
        'name': ASSET, 'digest': 'sha256:' + 'a' * 64,
        'browser_download_url': f'https://github.com/{REPOSITORY}/releases/download/v{version}/{ASSET}'}]}


class UpdateTests(unittest.TestCase):
    def test_dual_core_release_is_rejected(self):
        old = release('9.0.0')
        old_asset = 'Chrome-vpn-for-cottonclub-Windows-x64.zip'
        old['assets'][0]['name'] = old_asset
        old['assets'][0]['browser_download_url'] = (
            f'https://github.com/{REPOSITORY}/releases/download/v9.0.0/{old_asset}')
        with self.assertRaises(ValueError):
            parse_release(old, '1.1.0')

    def test_numeric_version_comparison_and_no_downgrade(self):
        self.assertTrue(parse_release(release('1.0.10'), '1.0.9')['available'])
        self.assertFalse(parse_release(release('1.0.2'), '1.0.3')['available'])
        self.assertFalse(parse_release(release('1.0.3'), '1.0.3')['available'])

    def test_previous_system_wide_singbox_package_is_rejected(self):
        old = release('9.0.0')
        old_asset = 'Chrome-vpn-for-cottonclub-sing-box-Windows-x64.zip'
        old['assets'][0]['name'] = old_asset
        old['assets'][0]['browser_download_url'] = (
            f'https://github.com/{REPOSITORY}/releases/download/v9.0.0/{old_asset}')
        with self.assertRaises(ValueError):
            parse_release(old, '1.2.0')

    def test_rejects_foreign_asset_missing_digest_and_prerelease(self):
        wrong_url = release()
        wrong_url['assets'][0]['browser_download_url'] = 'https://example.org/payload.zip'
        no_digest = release()
        no_digest['assets'][0]['digest'] = ''
        preview = release()
        preview['prerelease'] = True
        for item in (wrong_url, no_digest, preview, release('1.0.4-rc1')):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_release(item, '1.0.3')

    def test_native_host_never_starts_update_while_connected(self):
        host = Host(io.BytesIO(), core=Mock())
        host.connected = True
        with patch('native_host.launch_update') as launch:
            with self.assertRaises(RuntimeError):
                host.dispatch({'action': 'installUpdate'})
            launch.assert_not_called()

    def test_source_mode_never_launches_arbitrary_programs(self):
        with patch('updates.subprocess.Popen') as popen:
            with self.assertRaises(RuntimeError):
                launch_update()
            popen.assert_not_called()

    def test_helper_outside_user_install_cannot_start_updater(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'other/releases/test/host/CottonClub-Host.exe'
            with patch('updates.sys.frozen', True, create=True), patch('updates.sys.executable', str(executable)), \
                    patch.dict('os.environ', {'LOCALAPPDATA': directory}), patch('updates.subprocess.Popen') as popen:
                with self.assertRaises(RuntimeError):
                    launch_update()
                popen.assert_not_called()

    def test_installed_helper_launches_only_fixed_updater_and_passes_its_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'Chrome VPN for CottonClub'
            executable = base / 'releases/test/host/CottonClub-Host.exe'
            executable.parent.mkdir(parents=True)
            (base / 'Update.ps1').write_text('# test', encoding='utf-8')
            with patch('updates.sys.frozen', True, create=True), patch('updates.sys.executable', str(executable)), \
                    patch.dict('os.environ', {'LOCALAPPDATA': directory}), patch('updates.os.getpid', return_value=123), \
                    patch('updates.subprocess.Popen') as popen:
                self.assertTrue(launch_update()['started'])
                arguments = popen.call_args.args[0]
                self.assertEqual(arguments[-3:], [str(base / 'Update.ps1'), '-WaitForHostPid', '123'])


if __name__ == '__main__':
    unittest.main()

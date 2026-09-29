"""Regression checks for the installation privilege boundary and host identity."""
import json
from pathlib import Path
import re
import unittest

from host_config import HOST_NAME, EXTENSION_ID

ROOT = Path(__file__).resolve().parents[1]


class UserInstallTests(unittest.TestCase):
    def test_installer_and_uninstaller_only_target_current_user(self):
        for filename in ('Install.ps1', 'Uninstall.ps1'):
            source = (ROOT / filename).read_text(encoding='utf-8-sig')
            with self.subTest(filename=filename):
                self.assertNotRegex(source, r'(?i)-Verb\s+RunAs|::LocalMachine|HKLM|CommonDesktopDirectory|CommonPrograms')
                self.assertNotIn("GetFolderPath('ProgramFiles')", source)
                self.assertIn('RegistryHive]::CurrentUser', source)
                self.assertIn("GetFolderPath('LocalApplicationData')", source)
                self.assertIn("GetFolderPath('DesktopDirectory')", source)
                self.assertIn("GetFolderPath('Programs')", source)
                self.assertIn(HOST_NAME, source)

    def test_no_elevation_in_bootstrap_or_updater(self):
        for filename in ('Bootstrap.ps1', 'Update.ps1', 'src/updates.py'):
            source = (ROOT / filename).read_text(encoding='utf-8-sig')
            with self.subTest(filename=filename):
                self.assertNotRegex(source, r'(?i)-Verb\s+RunAs|ShellExecute|requireAdministrator')
                self.assertNotIn("os.environ['ProgramFiles']", source)

    def test_extension_and_user_host_share_identity_without_old_machine_host(self):
        source = (ROOT / 'extension/background.js').read_text(encoding='utf-8')
        host = re.search(r"const HOST = '([^']+)'", source)[1]
        self.assertEqual(host, HOST_NAME)
        self.assertEqual(HOST_NAME, 'com.cottonclub.hysteria2')
        self.assertNotIn('com.projectzxc.admin', source)
        manifest = json.loads((ROOT / 'extension/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], '1.2.0')
        self.assertIn('nativeMessaging', manifest['permissions'])
        self.assertIn(EXTENSION_ID, (ROOT / 'Install.ps1').read_text(encoding='utf-8-sig'))

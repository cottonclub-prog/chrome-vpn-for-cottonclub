import tempfile
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from app_paths import APP_DIRECTORY, APP_NAME
from device_identity import device_id, subscription_headers
from runtime import DATA
from native_host import Host


class DeviceIdentityTests(unittest.TestCase):
    def test_helper_data_and_identity_use_one_application_directory(self):
        self.assertEqual(DATA, APP_DIRECTORY)
        self.assertEqual(APP_DIRECTORY.name, APP_NAME)
        with tempfile.TemporaryDirectory() as directory, patch('device_identity.APP_DIRECTORY', Path(directory)):
            value = device_id()
            self.assertRegex(value, r'^[a-f0-9]{32}$')
            self.assertEqual(device_id(), value)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['device-id.txt'])

    def test_migrated_identity_is_sent_unchanged_with_new_client_name(self):
        with tempfile.TemporaryDirectory() as directory, patch('device_identity.APP_DIRECTORY', Path(directory)):
            value = '1234567890abcdef1234567890abcdef'
            (Path(directory) / 'device-id.txt').write_text(value, encoding='ascii')
            headers = subscription_headers()
            self.assertEqual(headers['X-Hwid'], value)
            self.assertEqual(headers['X-Device-Model'], APP_NAME)
            self.assertTrue(headers['User-Agent'].startswith('cottonclub-vpn-for-chrome/'))

    def test_native_core_does_not_write_configuration_into_extension(self):
        self.assertEqual(Host(io.BytesIO()).core.data, APP_DIRECTORY)

    def test_corrupted_identity_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / 'device-id.txt'
            saved.write_text('invalid', encoding='ascii')
            with self.assertRaises(ValueError):
                device_id(directory)
            self.assertEqual(saved.read_text(encoding='ascii'), 'invalid')

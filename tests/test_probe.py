import unittest
from unittest.mock import Mock, patch

from runtime import check_connection


class ConnectionProbeTests(unittest.TestCase):
    def test_probe_uses_socks_with_remote_dns_and_ignores_system_proxy(self):
        session = Mock()
        session.get.return_value.text = '203.0.113.9\n'
        with patch('requests.Session') as factory:
            factory.return_value.__enter__.return_value = session
            self.assertEqual(check_connection(17892), '203.0.113.9')
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with(
            'https://api.ipify.org',
            proxies={'https': 'socks5h://127.0.0.1:17892'}, timeout=(8, 15))
        session.get.return_value.raise_for_status.assert_called_once()

    def test_probe_rejects_non_ip_response(self):
        with patch('requests.Session') as factory:
            factory.return_value.__enter__.return_value.get.return_value.text = '<html>login</html>'
            with self.assertRaises(ValueError):
                check_connection(17892)


if __name__ == '__main__':
    unittest.main()

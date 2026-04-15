# -*- coding: utf-8 -*-
"""Unit tests for Client.from_public_link URL parsing.

No live server required — tests only verify that the base URL
and token are extracted correctly from various public link formats.
"""
import unittest
from unittest.mock import patch, MagicMock
import owncloud


class TestFromPublicLink(unittest.TestCase):
    """Verify from_public_link correctly extracts base URL and token
    across all real-world public link formats."""

    def _call(self, url):
        """Call from_public_link with mocked anon_login, return (base_url, token)."""
        captured = {}

        with patch.object(owncloud.Client, 'anon_login') as mock_login:
            client = owncloud.Client.from_public_link(url)
            # Client.__init__ appends '/' to url
            captured['base_url'] = client.url
            captured['token'] = mock_login.call_args[0][0]

        return captured['base_url'], captured['token']

    def test_root_pretty_url(self):
        url, token = self._call('https://cloud.example.com/s/aBcDeFgH')
        self.assertEqual(url, 'https://cloud.example.com/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_root_non_pretty_url(self):
        url, token = self._call('https://cloud.example.com/index.php/s/aBcDeFgH')
        self.assertEqual(url, 'https://cloud.example.com/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_subpath_pretty_url(self):
        url, token = self._call('https://example.com/owncloud/s/aBcDeFgH')
        self.assertEqual(url, 'https://example.com/owncloud/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_subpath_non_pretty_url(self):
        url, token = self._call('https://example.com/owncloud/index.php/s/aBcDeFgH')
        self.assertEqual(url, 'https://example.com/owncloud/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_port_handling(self):
        url, token = self._call('https://cloud.example.com:8443/s/aBcDeFgH')
        self.assertEqual(url, 'https://cloud.example.com:8443/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_port_with_subpath(self):
        url, token = self._call('https://example.com:8443/owncloud/s/aBcDeFgH')
        self.assertEqual(url, 'https://example.com:8443/owncloud/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_port_with_subpath_non_pretty(self):
        url, token = self._call('https://example.com:8443/owncloud/index.php/s/aBcDeFgH')
        self.assertEqual(url, 'https://example.com:8443/owncloud/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_deep_subpath(self):
        url, token = self._call('https://example.com/apps/owncloud/s/aBcDeFgH')
        self.assertEqual(url, 'https://example.com/apps/owncloud/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_http_scheme(self):
        url, token = self._call('http://localhost/s/aBcDeFgH')
        self.assertEqual(url, 'http://localhost/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_http_localhost_with_port(self):
        url, token = self._call('http://localhost:8080/s/aBcDeFgH')
        self.assertEqual(url, 'http://localhost:8080/')
        self.assertEqual(token, 'aBcDeFgH')

    def test_folder_password_passed_through(self):
        with patch.object(owncloud.Client, 'anon_login') as mock_login:
            owncloud.Client.from_public_link(
                'https://cloud.example.com/s/aBcDeFgH',
                folder_password='secret'
            )
            mock_login.assert_called_once_with('aBcDeFgH', folder_password='secret')


if __name__ == '__main__':
    unittest.main()

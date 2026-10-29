# -*- coding: utf-8 -*-
"""Tests for public share links against a local fake of Nextcloud's public WebDAV.

The fake mimics a Nextcloud 35 installed under /nextcloud: the legacy
``public.php/webdav`` endpoint lists but refuses MKCOL/PUT (403), while
``public.php/dav/files/<token>`` allows them.
"""
import base64
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import nextcloud_client

WEBROOT = '/nextcloud'
TOKEN = 'AbCdEf123456789'
PASSWORD = 's3cret'


class FakePublicDav(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _handle(self):
        self.server.requests.append((self.command, self.path))
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''

        legacy = WEBROOT + '/public.php/webdav/'
        new = WEBROOT + '/public.php/dav/files/' + TOKEN + '/'

        if self.path.startswith(legacy):
            return self._reply(207 if self.command == 'PROPFIND' else 403)
        if not self.path.startswith(new):
            return self._reply(404)

        if self.server.password:
            expected = 'Basic ' + base64.b64encode(
                ('anonymous:' + self.server.password).encode()).decode()
            if self.headers.get('Authorization') != expected:
                return self._reply(401)

        rel = self.path[len(new) - 1:]
        if self.command == 'MKCOL':
            if rel in self.server.tree:
                return self._reply(405)
            self.server.tree[rel] = None
            return self._reply(201)
        if self.command == 'PUT':
            parent = rel.rsplit('/', 1)[0] + '/'
            if parent != '/' and parent not in self.server.tree:
                return self._reply(409)
            self.server.tree[rel] = body
            return self._reply(201)
        self._reply(405)

    do_MKCOL = do_PUT = do_PROPFIND = do_GET = _handle


class PublicShareTest(unittest.TestCase):
    password = ''

    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), FakePublicDav)
        self.server.requests = []
        self.server.tree = {}
        self.server.password = self.password
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.link = 'http://127.0.0.1:%d%s/s/%s' % (
            self.server.server_port, WEBROOT, TOKEN)

    def client(self, link=None):
        return nextcloud_client.Client.from_public_link(
            link or self.link, folder_password=self.password)

    def put_zip(self, client, remote_path):
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, 'result.zip')
            with open(local, 'wb') as f:
                f.write(b'PK-fake')
            return client.put_file(remote_path, local, chunked=False)

    def test_mkdir_and_put(self):
        client = self.client()
        self.assertTrue(client.mkdir('chest_ct'))
        self.assertTrue(self.put_zip(client, 'chest_ct/1.2.3.zip'))
        self.assertEqual(self.server.tree['/chest_ct/1.2.3.zip'], b'PK-fake')

    def test_mkdir_existing_folder_is_405(self):
        client = self.client()
        client.mkdir('chest_ct')
        with self.assertRaises(nextcloud_client.HTTPResponseError) as ctx:
            client.mkdir('chest_ct')
        self.assertEqual(ctx.exception.status_code, 405)

    def test_never_uses_legacy_endpoint(self):
        client = self.client()
        client.mkdir('a')
        self.put_zip(client, 'a/x.zip')
        self.assertTrue(self.server.requests)
        for _, path in self.server.requests:
            self.assertNotIn('public.php/webdav', path)
            self.assertIn('/public.php/dav/files/%s/' % TOKEN, path)

    def test_trailing_slash_in_link(self):
        client = self.client(self.link + '/')
        self.assertTrue(client.mkdir('a'))

    def test_legacy_endpoint_still_refuses_writes(self):
        # documents why the endpoint changed: same server, legacy URL -> 403
        client = nextcloud_client.Client(
            'http://127.0.0.1:%d%s/' % (self.server.server_port, WEBROOT))
        client._session = requests.session()
        client._webdav_url = client.url + 'public.php/webdav'
        client._davpath = WEBROOT + '/public.php/webdav'
        with self.assertRaises(nextcloud_client.HTTPResponseError) as ctx:
            client.mkdir('a')
        self.assertEqual(ctx.exception.status_code, 403)


class PasswordProtectedPublicShareTest(PublicShareTest):
    password = PASSWORD

    def test_wrong_password_is_401(self):
        client = nextcloud_client.Client.from_public_link(
            self.link, folder_password='wrong')
        with self.assertRaises(nextcloud_client.HTTPResponseError) as ctx:
            client.mkdir('a')
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == '__main__':
    unittest.main()

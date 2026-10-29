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

    def _multistatus(self, new, rel):
        if rel != '/' and rel not in self.server.tree:
            return self._reply(404)
        entries = [rel] + sorted(
            p for p in self.server.tree
            if p != rel and p.startswith(rel) and '/' not in p[len(rel):].rstrip('/'))
        body = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
        for e in entries:
            body += ('<d:response><d:href>%s</d:href><d:propstat><d:prop>'
                     '<d:resourcetype/></d:prop>'
                     '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                     % (new[:-1] + e))
        body = (body + '</d:multistatus>').encode()
        self.send_response(207)
        self.send_header('Content-Type', 'application/xml')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        self.server.requests.append((self.command, self.path))
        self.server.auth_headers.append(self.headers.get('Authorization'))
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
                ('anonymous:' + self.server.password).encode('utf-8')).decode()
            if self.headers.get('Authorization') != expected:
                return self._reply(401)

        rel = self.path[len(new) - 1:]
        if self.command == 'PROPFIND':
            return self._multistatus(new, rel)
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
        self.server.auth_headers = []
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

    def test_list_strips_dav_path(self):
        client = self.client()
        client.mkdir('a')
        client.mkdir('a/b')
        self.assertEqual([f.path for f in client.list('/')], ['/a/'])
        self.assertEqual([f.path for f in client.list('a')], ['/a/b/'])

    def test_large_file_is_not_chunked(self):
        client = self.client()
        client.mkdir('a')
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, 'big.zip')
            with open(local, 'wb') as f:
                f.write(b'x' * (11 * 1024 * 1024))
            self.assertTrue(client.put_file('a/big.zip', local))  # chunked=True is the default
        self.assertEqual(len(self.server.tree['/a/big.zip']), 11 * 1024 * 1024)
        for _, path in self.server.requests:
            self.assertNotIn('chunking', path)

    def test_authorization_header(self):
        self.client().mkdir('a')
        if self.password:
            self.assertTrue(self.server.auth_headers[-1].startswith('Basic '))
        else:
            self.assertEqual(self.server.auth_headers, [None])

    def test_link_variants(self):
        base = 'http://127.0.0.1:%d' % self.server.server_port
        for link in (
            base + WEBROOT + '/index.php/s/' + TOKEN,
            base + WEBROOT + '/s/' + TOKEN + '/download',
            base + WEBROOT + '/s/' + TOKEN + '?path=%2Fa',
        ):
            self.assertTrue(self.client(link).mkdir('v'), link)
            self.server.tree.clear()

    def test_link_without_token_is_rejected(self):
        with self.assertRaises(ValueError):
            self.client('http://127.0.0.1/nextcloud/index.php/login')


class PasswordProtectedPublicShareTest(PublicShareTest):
    password = PASSWORD

    def test_non_latin1_password(self):
        self.server.password = u'\u043f\u0430\u0440\u043e\u043b\u044c'
        client = nextcloud_client.Client.from_public_link(
            self.link, folder_password=self.server.password)
        self.assertTrue(client.mkdir('a'))

    def test_wrong_password_is_401(self):
        client = nextcloud_client.Client.from_public_link(
            self.link, folder_password='wrong')
        with self.assertRaises(nextcloud_client.HTTPResponseError) as ctx:
            client.mkdir('a')
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == '__main__':
    unittest.main()

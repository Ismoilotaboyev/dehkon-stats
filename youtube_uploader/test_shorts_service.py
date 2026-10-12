import contextlib
import hashlib
import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import shorts_service as app


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.temp.name)
        app.BASE = 'https://example.test'
        app.CALLBACK = app.BASE + '/oauth/callback'
        app.ADMIN_HASH = app.digest('test-only-login-code')
        app.LOGIN_ATTEMPTS.clear()
        app.initialize()
        self.server = app.http.server.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path='/', data=None, cookie='', origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Origin': origin or app.BASE}
        if cookie:
            headers['Cookie'] = cookie
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        conn.request(method, path, urlencode(data) if data is not None else None, headers)
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read().decode())
        conn.close()
        return result

    def login(self):
        status, headers, _ = self.request('POST', '/login', {'code':'test-only-login-code'})
        self.assertEqual(status, 303)
        cookie = headers['Set-Cookie'].split(';')[0]
        status, _, body = self.request('GET', cookie=cookie)
        self.assertEqual(status, 200)
        csrf = re.search("name='csrf' value='([^']+)'", body).group(1)
        return cookie, csrf

    def seed_job(self, jid='100'):
        channel = {'id':'UCtest', 'title':'Test channel'}
        app.put('channel', channel)
        app.put('enabled', True)
        path = app.DATA / 'media' / (jid + '.mp4')
        path.write_bytes(b'test-video-bytes')
        with app.db() as con:
            con.execute("INSERT INTO jobs(id,channel,created,status,payload) VALUES(?,?,?,'pending',?)", (jid, channel['id'], time.time(), json.dumps({'media_url':'https://cdninstagram.com/test', 'timestamp':'2026-10-12T00:00:00Z'})))
            job = dict(con.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        return job, path, channel

    def test_owner_and_csrf_protect_secrets(self):
        app.put('client', {'client_id':'sensitive-client', 'client_secret':'never-display'})
        status, _, body = self.request('GET')
        self.assertEqual(status, 200)
        self.assertNotIn('never-display', body)
        self.assertEqual(self.request('POST','/pause', {'csrf':'fake'})[0],403)
        self.assertEqual(self.request('POST','/login', {'code':'test-only-login-code'},origin='https://evil.test')[0],403)
        cookie, csrf = self.login()
        self.assertEqual(self.request('POST','/pause', {'csrf':'wrong'},cookie=cookie)[0],403)
        self.assertEqual(self.request('POST','/pause', {'csrf':csrf},cookie=cookie)[0],303)

    def test_disabled_worker_has_no_network(self):
        with patch.object(app,'stories') as stories:
            app.tick()
        stories.assert_not_called()

    def test_activation_baselines_existing_stories(self):
        cookie, csrf = self.login()
        channel = {'id':'UCtest','title':'Test channel'}
        app.put('channel',channel)
        media = [{'id':'101','media_type':'VIDEO','timestamp':'2026-10-11T00:00:00Z'}]
        with patch.object(app,'channel_info',return_value=channel), patch.object(app,'stories',return_value=media):
            self.assertEqual(self.request('POST','/enable',{'csrf':csrf,'privacy':'private'},cookie=cookie)[0],303)
        with app.db() as con:
            self.assertEqual(con.execute("SELECT status FROM jobs WHERE id='101'").fetchone()[0],'baseline')
        self.assertTrue(app.get('enabled'))
        self.assertEqual(app.get('privacy'),'private')

    def test_oauth_state_replay_is_rejected(self):
        cookie, csrf = self.login()
        app.put('client',{'client_id':'fake.apps.googleusercontent.com','client_secret':'local-test-secret'})
        status, headers, _ = self.request('POST','/connect',{'csrf':csrf},cookie=cookie)
        self.assertEqual(status,303)
        self.assertIn('code_challenge_method=S256',headers['Location'])
        with patch.object(app,'api_http') as network:
            self.assertEqual(self.request('GET','/oauth/callback?state=wrong&code=fake',cookie=cookie)[0],400)
        network.assert_not_called()

    def test_resume_completed_upload_does_not_insert_again(self):
        job,path,channel = self.seed_job()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        job.update(session_url='https://www.googleapis.com/upload/session',sha=sha,size=path.stat().st_size)
        app.job_update(job['id'],session_url=job['session_url'],sha=sha,size=job['size'])
        calls=[]
        def fake(method,url,**kw):
            calls.append((method,url,kw))
            return 200,{}, {'id':'abcdefghijk','status':{'privacyStatus':'public'}}
        with patch.object(app,'download',return_value=path), patch.object(app,'short_metadata',return_value=30), patch.object(app,'access_token',return_value='test-only'), patch.object(app,'channel_info',return_value=channel), patch.object(app,'api_http',side_effect=fake):
            app.upload(job)
        self.assertEqual([x[0] for x in calls],['PUT'])
        self.assertFalse(path.exists())
        with app.db() as con:
            self.assertEqual(con.execute("SELECT status FROM jobs WHERE id='100'").fetchone()[0],'uploaded')

    def test_resume_uses_server_offset(self):
        job,path,channel = self.seed_job()
        calls=[]
        responses=[(200,{'Location':'https://www.googleapis.com/upload/session'},{}),(308,{'Range':'bytes=0-3'},{}),(201,{}, {'id':'abcdefghijk','status':{'privacyStatus':'private'}})]
        def fake(method,url,**kw):
            calls.append((method,kw))
            return responses.pop(0)
        with patch.object(app,'download',return_value=path), patch.object(app,'short_metadata',return_value=30), patch.object(app,'access_token',return_value='test-only'), patch.object(app,'channel_info',return_value=channel), patch.object(app,'api_http',side_effect=fake):
            app.upload(job)
        self.assertEqual(calls[2][1]['data'],b'-video-bytes')
        self.assertEqual(calls[2][1]['headers']['Content-Range'],'bytes 4-15/16')

    def test_expired_upload_is_held_for_review(self):
        job,path,channel = self.seed_job()
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        job.update(session_url='https://www.googleapis.com/upload/session',sha=sha,size=path.stat().st_size)
        with patch.object(app,'download',return_value=path), patch.object(app,'short_metadata',return_value=30), patch.object(app,'access_token',return_value='test-only'), patch.object(app,'channel_info',return_value=channel), patch.object(app,'api_http',return_value=(404,{},{})) as network:
            app.upload(job)
        self.assertEqual(network.call_count,1)
        with app.db() as con:
            self.assertEqual(con.execute("SELECT status FROM jobs WHERE id='100'").fetchone()[0],'review')

    def test_wrong_channel_pauses_before_any_upload(self):
        job,path,channel=self.seed_job()
        with patch.object(app,'download',return_value=path), patch.object(app,'short_metadata',return_value=30), patch.object(app,'access_token',return_value='test-only'), patch.object(app,'channel_info',return_value={'id':'UCwrong','title':'Other'}), patch.object(app,'api_http') as network:
            with self.assertRaises(app.SafeError):
                app.upload(job)
        network.assert_not_called()
        self.assertFalse(app.get('enabled'))


if __name__ == '__main__':
    unittest.main()

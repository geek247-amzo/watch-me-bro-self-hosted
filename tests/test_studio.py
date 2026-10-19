import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('studio', ROOT / 'app.py')
studio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(studio)


class PlanValidation(unittest.TestCase):
    def setUp(self):
        self.source = {'abc': {'id': 'abc', 'duration': 10}}
        self.plan = {'title': 'Test', 'format': 'vertical', 'audio': 'mute',
                     'cuts': [{'source': 'abc', 'start': 0, 'end': 5}],
                     'captions': [{'start': 0, 'end': 2, 'text': 'An authentic moment'}]}

    def test_valid(self):
        self.assertEqual(studio.validate_plan(self.plan, self.source)['cuts'][0]['end'], 5)

    def test_source_bounds(self):
        self.plan['cuts'][0]['end'] = 11
        with self.assertRaises(ValueError):
            studio.validate_plan(self.plan, self.source)

    def test_unknown_source(self):
        self.plan['cuts'][0]['source'] = '../../etc/passwd'
        with self.assertRaises(ValueError):
            studio.validate_plan(self.plan, self.source)

    def test_nonfinite(self):
        self.plan['cuts'][0]['end'] = float('nan')
        with self.assertRaises(ValueError):
            studio.validate_plan(self.plan, self.source)

    def test_caption_bounds(self):
        self.plan['captions'][0]['end'] = 6
        with self.assertRaises(ValueError):
            studio.validate_plan(self.plan, self.source)

    def test_packaging_bounds(self):
        self.plan['overlay'] = {'headline': 'A hook', 'cta': 'Subscribe', 'brand': 'WMB', 'outro_seconds': 11}
        with self.assertRaises(ValueError):
            studio.validate_plan(self.plan, self.source)


class ProviderSecurity(unittest.TestCase):
    def test_provider_discovery_uses_fixed_official_host_without_key_in_url(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return b'{"models":[{"name":"models/example-model"}]}'
        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()
        opener = Opener()
        with patch.object(studio.urllib.request, 'build_opener', return_value=opener):
            models = studio.provider_models('google', 'synthetic-not-a-real-key')
        self.assertEqual(models, ['example-model'])
        self.assertEqual(opener.request.full_url, 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000')
        self.assertEqual(opener.request.get_header('X-goog-api-key'), 'synthetic-not-a-real-key')
        self.assertNotIn('synthetic-not-a-real-key', opener.request.full_url)
        self.assertEqual(opener.timeout, 15)

    def test_redirects_are_rejected(self):
        self.assertIsNone(studio.NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://evil.example'))

    def test_chat_uses_fixed_provider_host_and_parses_usage(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return b'{"choices":[{"message":{"content":"{\\"suggestions\\":[]}"}}],"usage":{"prompt_tokens":12,"completion_tokens":5}}'
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return Response()
        opener = Opener()
        with patch.object(studio.urllib.request, 'build_opener', return_value=opener):
            result = studio.provider_chat('openrouter', 'synthetic-not-a-real-key', 'example/model', 'synthetic prompt', 700)
        self.assertEqual(opener.request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        self.assertNotIn('synthetic-not-a-real-key', opener.request.full_url)
        self.assertEqual(opener.timeout, 60)
        self.assertEqual(result[1], {'input_tokens': 12, 'output_tokens': 5})

class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='wmb-test-', dir=os.environ.get('WMB_TEST_MEDIA_ROOT'))
        cls.path = Path(cls.tmp.name)
        cls.password = 'test-only-not-a-deployment-password'
        (cls.path / 'password').write_text(cls.password)
        (cls.path / 'crypto-key').write_bytes(b'x' * 32)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / 'app.py')], env={**os.environ,
            'WMB_DATA': str(cls.path / 'data'), 'WMB_MEDIA': str(cls.path / 'media'),
            'WMB_AUTH': str(cls.path / 'password'), 'WMB_CRYPTO_KEY': str(cls.path / 'crypto-key'), 'WMB_PORT': str(cls.port)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.cookie = ''
        for _ in range(50):
            try:
                if cls.req('GET', '/health')[0] == 200:
                    break
            except ConnectionRefusedError:
                pass
            time.sleep(.1)
        else:
            if cls.proc.poll() is None:
                cls.proc.terminate()
            output, _ = cls.proc.communicate(timeout=5)
            raise AssertionError(f'Studio did not start: {output[:2000]}')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    @classmethod
    def req(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=30)
        h = {'X-WMB-Request': 'studio', 'Cookie': cls.cookie, **(headers or {})}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        conn.request(method, path, body, h)
        r = conn.getresponse()
        result = r.read()
        result = json.loads(result) if r.getheader('Content-Type') == 'application/json' else result
        status, response_headers = r.status, dict(r.getheaders())
        conn.close()
        return status, result, response_headers

    def test_full_pipeline(self):
        self.assertEqual(self.req('GET', '/api/workspace')[0], 401)
        status, icon, icon_headers = self.req('GET', '/favicon.ico')
        self.assertEqual(status, 200)
        self.assertIn(b'<svg', icon)
        self.assertEqual(icon_headers['Content-Type'], 'image/svg+xml')
        self.assertEqual(self.req('POST', '/api/login', {'password': self.password}, {'X-WMB-Request': ''})[0], 403)
        self.assertEqual(self.req('POST', '/api/login', {'password': self.password}, {'Origin': 'https://evil.test'})[0], 403)
        status, _, h = self.req('POST', '/api/login', {'password': self.password})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly; Secure; SameSite=Strict', h['Set-Cookie'])
        type(self).cookie = h['Set-Cookie'].split(';')[0]
        secret = 'synthetic-provider-key-never-a-real-credential'
        self.assertEqual(self.req('POST', '/api/provider-key', {'provider': 'openrouter', 'key': secret})[0], 200)
        status, provider_list, _ = self.req('GET', '/api/providers')
        self.assertEqual(status, 200)
        self.assertTrue(next(p for p in provider_list['providers'] if p['id'] == 'openrouter')['configured'])
        self.assertFalse(provider_list['storyboardEnabled'])
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as c:
            encrypted = c.execute('SELECT ciphertext FROM provider_credentials WHERE provider=?', ('openrouter',)).fetchone()[0]
            self.assertNotIn(secret.encode(), encrypted)
        self.assertEqual(self.req('POST', '/api/provider-key', {'provider': 'evil.example', 'key': secret})[0], 400)
        self.assertEqual(self.req('POST', '/api/provider-key/remove/openrouter', {})[0], 200)
        status, p, _ = self.req('POST', '/api/projects', {'title': 'Synthetic test production', 'mode': 'gaming', 'brand': 'Watch Me Bro'})
        self.assertEqual(status, 201)
        self.assertEqual(self.req('GET', '/settings')[0], 200)
        self.assertIn('routes', self.req('GET', '/api/creative/settings')[1])
        asset_raw = subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-filter_threads','1','-f','lavfi','-i','color=red:s=64x64','-frames:v','1','-c:v','png','-threads','1','-f','image2pipe','pipe:1'],check=True,stdout=subprocess.PIPE).stdout
        status, asset, _ = self.req('POST', '/api/asset-upload/'+p['id']+'/image', asset_raw, {'X-Filename':'test.png'})
        self.assertEqual(status, 201, asset)
        self.assertEqual(self.req('GET', '/asset/'+asset['id'])[0], 200)
        self.assertEqual(self.req('GET', '/asset/'+asset['id'],headers={'Range':'bytes=0-9'})[0],206)
        self.assertEqual(self.req('POST', '/api/asset-upload/'+p['id']+'/image',b'<svg>no</svg>')[0],400)
        media = self.path / 'test.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '4',
                        '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', str(media)], check=True)
        source_bytes = media.read_bytes()
        status, source, _ = self.req('POST', '/api/upload/' + p['id'], source_bytes, {'X-Filename': 'test.mp4'})
        self.assertEqual(status, 201, source)
        self.assertGreater(source['duration'], 3)
        self.assertEqual(self.req('POST', '/api/upload/' + p['id'], source_bytes, {'X-Filename': 'duplicate.mp4'})[1]['duplicate'], True)
        self.assertEqual(self.req('POST', '/api/upload/' + p['id'], b'not-video', {'X-Filename': 'test.mp4'})[0], 400)
        self.assertEqual(self.req('GET', '/file/' + source['id'], headers={'Range': 'bytes=0-99'})[0], 206)
        self.assertEqual(self.req('GET', '/file/' + source['id'], headers={'Range': 'bytes=999999999-'})[0], 416)
        plan = {'title': 'Synthetic captioned render', 'format': 'landscape', 'resolution': '1080p', 'audio': 'original',
                'overlay': {'headline': 'A synthetic hook', 'intro': 'WMB %{test} intro', 'intro_seconds': 2,
                            'cta': 'Like and subscribe', 'brand': 'WMB', 'outro_seconds': 3.5},
                'cuts': [{'source': source['id'], 'start': 0, 'end': 2}, {'source': source['id'], 'start': 2, 'end': 3}],
                'captions': [{'start': 0, 'end': 2, 'text': 'Synthetic QA footage only'}]}
        self.assertEqual(self.req('POST', '/api/plan', {'project': p['id'], 'plan': plan})[0], 200)
        status, job, _ = self.req('POST', '/api/render', {'project': p['id'], 'plan': plan})
        self.assertEqual(status, 202)
        for _ in range(120):
            jobs = self.req('GET', '/api/workspace')[1]['jobs']
            state = next(j for j in jobs if j['id'] == job['id'])
            if state['state'] in ['review', 'failed']:
                break
            time.sleep(.5)
        self.assertEqual(state['state'], 'review', state)
        self.assertEqual(state['progress']['percent'],100)
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as c:
            count=c.execute('SELECT count(*) FROM render_steps WHERE job=?',(job['id'],)).fetchone()[0]
            expected=len(studio.render_progress.stages(plan))
            self.assertEqual(count,expected)
            detail=json.loads(c.execute('SELECT body FROM render_progress WHERE job=?',(job['id'],)).fetchone()[0])
            self.assertEqual(detail['index'],expected)
        self.assertFalse(list((self.path/'data'/'render-progress').glob('*.stats')))
        self.assertEqual(self.req('GET', f"/file/{job['id']}/video.mp4")[0], 200)
        rendered_metadata = studio.probe(self.path / 'media' / 'exports' / job['id'] / 'video.mp4')
        self.assertAlmostEqual(rendered_metadata[0], 8.5, delta=.4)
        dimensions = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', str(self.path / 'media' / 'exports' / job['id'] / 'video.mp4')]))['streams'][0]
        self.assertEqual(dimensions, {'width': 1920, 'height': 1080})
        srt = self.req('GET', f"/file/{job['id']}/captions.srt")
        self.assertEqual(srt[0], 200)
        self.assertIn(b'00:00:02,000 --> 00:00:04,000', srt[1])
        manifest = self.req('GET', f"/file/{job['id']}/manifest.json")[1]
        self.assertEqual(manifest['sources'][0]['sha256'], __import__('hashlib').sha256(source_bytes).hexdigest())
        self.assertEqual(self.req('POST', '/api/review', {'job': job['id'], 'checks': {}, 'note': 'Incomplete review'})[0], 400)
        status, r, _ = self.req('POST', '/api/review', {'job': job['id'], 'checks': {k: True for k in studio.SAFETY}, 'note': 'Synthetic QA owner approval'})
        self.assertEqual(status, 200)
        self.assertEqual(r['publishing'], 'disabled')
        # Muted vertical output is independently rendered; approvals never carry to a new version.
        plan.update(format='vertical', audio='mute')
        status, vertical, _ = self.req('POST', '/api/render', {'project': p['id'], 'plan': plan})
        self.assertEqual(status, 202)
        for _ in range(120):
            state = next(j for j in self.req('GET', '/api/workspace')[1]['jobs'] if j['id'] == vertical['id'])
            if state['state'] in ['review', 'failed']:
                break
            time.sleep(.5)
        self.assertEqual(state['state'], 'review', state)
        metadata = studio.probe(self.path / 'media' / 'exports' / vertical['id'] / 'video.mp4')
        self.assertAlmostEqual(metadata[0], 8.5, delta=.4)
        dimensions = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', str(self.path / 'media' / 'exports' / vertical['id'] / 'video.mp4')]))['streams'][0]
        self.assertEqual(dimensions, {'width': 1080, 'height': 1920})
        self.assertEqual(len(self.req('GET', '/api/workspace')[1]['reviews']), 1)
        # Paid storyboard requests are allowed only for a verified model with an explicit local budget.
        self.assertEqual(self.req('POST', '/api/provider-key', {'provider': 'openrouter', 'key': secret})[0], 200)
        # Seed a synthetic catalogue result directly; provider HTTP behavior is separately mocked above.
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as c:
            c.execute('INSERT INTO provider_models VALUES(?,?,?)', ('openrouter', 'synthetic/storyboard-model', time.time()))
        self.assertEqual(self.req('POST', '/api/provider-budget', {'provider': 'openrouter', 'model': 'unverified',
            'inputUsdPerMillion': 1, 'outputUsdPerMillion': 2, 'monthlyUsdCap': .1})[0], 400)
        self.assertEqual(self.req('POST', '/api/provider-budget', {'provider': 'openrouter', 'model': 'synthetic/storyboard-model',
            'inputUsdPerMillion': 1, 'outputUsdPerMillion': 2, 'monthlyUsdCap': .000001})[0], 200)
        status, storyboard, _ = self.req('POST', '/api/ai/storyboard', {'provider': 'openrouter', 'project': p['id'],
            'source': source['id'], 'transcript': [{'start': 0, 'end': 2, 'text': 'Synthetic test excerpt'}]})
        self.assertEqual(status, 400, storyboard)
        self.assertIn('exceed', storyboard['error'])
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as c:
            self.assertIsNone(c.execute('SELECT reserved_usd FROM provider_usage WHERE provider=?', ('openrouter',)).fetchone())
        self.assertEqual(self.req('GET', '/api/providers')[1]['providers'][0]['id'], 'anthropic')
        # Visual analysis quotes and admission never contact a provider without explicit consent.
        self.assertEqual(self.req('POST', '/api/analysis/quote', {'source': source['id'], 'project': p['id']})[0], 400)
        self.assertEqual(self.req('POST', '/api/provider-key', {'provider': 'openai', 'key': secret})[0], 200)
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as c:
            c.execute('INSERT INTO provider_models VALUES(?,?,?)', ('openai', 'gpt-5', time.time()))
        self.assertEqual(self.req('POST', '/api/provider-budget', {'provider': 'openai', 'model': 'gpt-5',
            'inputUsdPerMillion': 1.25, 'outputUsdPerMillion': 10, 'monthlyUsdCap': 10})[0], 200)
        analysis_body = {'source': source['id'], 'project': p['id'], 'interval': 1}
        status, quote, _ = self.req('POST', '/api/analysis/quote', analysis_body)
        self.assertEqual(status, 200)
        self.assertGreater(quote['frameCount'], 0)
        self.assertEqual(self.req('POST', '/api/analysis', {**analysis_body, 'quote': quote['quote'], 'requestId': 'synthetic-analysis-request'})[0], 400)
        self.assertTrue(self.req('GET', '/api/workspace')[1]['capabilities']['visualGameplayAnalysis'])
        # A cropped single-clip export preserves the saved multi-clip project plan.
        previous_plan = next(r['body'] for r in self.req('GET', '/api/workspace')[1]['plans'] if r['project'] == p['id'])
        one = {'title':'Cropped single clip','format':'vertical','resolution':'720p','audio':'mute','captions':[],
               'cuts':[{'source':source['id'],'start':1,'end':1.3,'crop':{'mode':'crop','x':.5,'y':0,'width':.5,'height':1}}]}
        status, single, _ = self.req('POST','/api/render',{'project':p['id'],'plan':one,'preservePlan':True})
        self.assertEqual(status,202,single)
        self.assertEqual(next(r['body'] for r in self.req('GET','/api/workspace')[1]['plans'] if r['project']==p['id']),previous_plan)
        for _ in range(60):
            state=next(j for j in self.req('GET','/api/workspace')[1]['jobs'] if j['id']==single['id'])
            if state['state'] in ['review','failed']:break
            time.sleep(.2)
        self.assertEqual(state['state'],'review',state)
        self.assertEqual(json.loads(state['body'])['cuts'][0]['crop']['x'],.5)
        # LM Studio LAN configuration: optional encrypted token, explicit trust and zero cloud rates.
        self.assertIsNone(self.req('GET','/api/lmstudio')[1]['config'])
        self.assertEqual(self.req('POST','/api/lmstudio',{'baseUrl':'http://127.0.0.1:1234/v1','trustLan':True})[0],400)
        self.assertEqual(self.req('POST','/api/lmstudio',{'baseUrl':'http://10.0.0.12:1234/v1'})[0],400)
        local_secret='synthetic-local-token-never-real'
        self.assertEqual(self.req('POST','/api/lmstudio',{'baseUrl':'http://10.0.0.12:1234/v1','token':local_secret,'trustLan':True})[0],200)
        config=self.req('GET','/api/lmstudio')[1]
        self.assertEqual(config['config']['base_url'],'http://10.0.0.12:1234/v1')
        self.assertNotIn(local_secret,json.dumps(config))
        with sqlite3.connect(self.path/'data'/'studio.sqlite') as c:
            self.assertNotIn(local_secret.encode(),c.execute("SELECT ciphertext FROM provider_credentials WHERE provider='lmstudio'").fetchone()[0])
            c.execute("INSERT INTO provider_models VALUES('lmstudio','local/vision',?)",(time.time(),))
            c.execute("INSERT INTO lmstudio_models VALUES('local/vision',1)")
        self.assertEqual(self.req('POST','/api/creative/route',{'feature':'analysis','provider':'lmstudio','model':'local/vision'})[0],200)
        status,local_quote,_=self.req('POST','/api/analysis/quote',analysis_body)
        self.assertEqual(status,200,local_quote);self.assertEqual(local_quote['spec']['upperCostUsd'],0)
        self.assertEqual(local_quote['spec']['localEndpoint'],'http://10.0.0.12:1234/v1')
        self.assertEqual(self.req('POST','/api/lmstudio',{'baseUrl':'http://10.0.0.13:1234/v1','trustLan':True})[0],400,'Never silently forward old host token')
        self.assertEqual(self.req('POST','/api/lmstudio',{'baseUrl':'http://10.0.0.13:1234/v1','token':'','trustLan':True})[0],200)
        self.assertEqual(self.req('GET','/api/lmstudio')[1]['models'],[])
        self.assertEqual(self.req('POST','/api/provider-key/remove/lmstudio',{})[0],200)
        self.assertEqual(self.req('POST','/api/analysis/quote',analysis_body)[0],400,'No automatic fallback to paid OpenAI')
        # SQLite backup API gives a consistent copy even with WAL enabled.
        with sqlite3.connect(self.path / 'data' / 'studio.sqlite') as src, sqlite3.connect(self.path / 'backup.sqlite') as dest:
            src.backup(dest)
            self.assertEqual(dest.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.req('POST', '/api/logout', {})[0], 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)

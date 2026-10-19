import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

import app
import creative
import highlights
import local_ai


class LocalTransport(unittest.TestCase):
    def test_sign_in_is_not_blocked_by_the_video_upload_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            password=Path(tmp)/'password';password.write_text('synthetic-login-password')
            statuses=[]
            handler=SimpleNamespace(connection=SimpleNamespace(settimeout=lambda _:None),headers={'X-WMB-Request':'studio'},path='/api/login',client_address=('127.0.0.1',1234),payload=lambda:{'password':'synthetic-login-password'},send=lambda status,*_args,**_kwargs:statuses.append(status))
            with patch.object(app,'AUTH',password),patch.object(app,'attempts',{}):
                app.lock.acquire()
                worker=threading.Thread(target=app.Handler.do_POST,args=(handler,),daemon=True)
                try:worker.start();worker.join(timeout=1);blocked=worker.is_alive()
                finally:app.lock.release();worker.join(timeout=2)
                self.assertFalse(blocked);self.assertEqual(statuses,[200])

    def test_endpoint_only_allows_literal_lan_hosts_and_fixed_api_root(self):
        self.assertEqual(local_ai.endpoint('http://10.0.0.12:1234'),'http://10.0.0.12:1234/v1')
        self.assertEqual(local_ai.endpoint('https://10.0.0.5:8443/v1/'),'https://10.0.0.5:8443/v1')
        for url in ['http://127.0.0.1:1234','http://169.254.169.254:1234','http://8.8.8.8:1234','http://localhost:1234','http://10.0.0.12','http://10.0.0.12:80','http://user:secret@10.0.0.12:1234','http://10.0.0.12:1234/v1?key=secret','http://10.0.0.12:1234/private','file:///etc/passwd','http://[::1]:1234','http://100.100.100.200:1234','http://10.0.0.12:1234/#fragment']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):local_ai.endpoint(url)

    def test_transport_optional_auth_no_proxy_redirect_and_no_sensitive_error(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,_):return b'{"data":[]}'
        class Opener:
            def open(self,request,timeout):self.request,self.timeout=request,timeout;return Response()
        opener=Opener()
        with patch.object(local_ai.urllib.request,'build_opener',return_value=opener) as build:
            local_ai.request('http://10.0.0.12:1234/v1','','/v1/models')
            self.assertIsNone(opener.request.get_header('Authorization'))
            self.assertEqual(opener.timeout,20)
            self.assertEqual(build.call_args.args[0].proxies,{})
            local_ai.request('http://10.0.0.12:1234/v1','synthetic-token','/v1/chat/completions',{'model':'test'})
            self.assertEqual(opener.request.get_header('Authorization'),'Bearer synthetic-token')
            self.assertNotIn('synthetic-token',opener.request.full_url)
        self.assertIsNone(local_ai.RejectRedirect().redirect_request(None,None,302,'',{},'https://evil.example'))
        with self.assertRaises(ValueError):local_ai.request('http://10.0.0.12:1234/v1','','/api/v1/models/load',{})
        opener.open=lambda *_args,**_kwargs:(_ for _ in ()).throw(urllib.error.HTTPError('redacted',401,'synthetic-secret-response',None,None))
        with patch.object(local_ai.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError) as error:local_ai.request('http://10.0.0.12:1234/v1','synthetic-token','/v1/models')
            self.assertNotIn('synthetic-token',str(error.exception));self.assertNotIn('synthetic-secret-response',str(error.exception))

    def test_catalogue_vision_metadata_and_legacy_text_only_fallback(self):
        catalogue={'data':[{'id':'local/text'},{'id':'local/vision'},{'id':'text-embedding-test'}]}
        native={'models':[{'key':'local/text','type':'llm','capabilities':{'vision':False}}, {'key':'vision-file','type':'llm','loaded_instances':[{'id':'local/vision'}],'capabilities':{'vision':True}}]}
        with patch.object(local_ai,'request',side_effect=[catalogue,native]):
            models=local_ai.discover('http://10.0.0.12:1234/v1','')
            self.assertEqual(models,[{'model':'local/text','vision':False},{'model':'local/vision','vision':True}])
        with patch.object(local_ai,'request',side_effect=[catalogue,ValueError('Native metadata unavailable')]):
            self.assertFalse(any(m['vision'] for m in local_ai.discover('http://10.0.0.12:1234/v1','')))

    def test_text_and_vision_payloads_and_incomplete_response(self):
        response={'choices':[{'finish_reason':'stop','message':{'content':'```json\n{"highlights":[]}\n```'}}],'usage':{'prompt_tokens':12,'completion_tokens':5}}
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'frame.jpg';image.write_bytes(b'synthetic-frame')
            with patch.object(local_ai,'request',return_value=response) as request:
                output,usage=local_ai.chat('http://10.0.0.12:1234/v1','','local/vision','Evidence',6000,[(2,image)])
                self.assertEqual(json.loads(output),{'highlights':[]});self.assertEqual(usage['prompt_tokens'],12)
                payload=request.call_args.args[3]
                self.assertEqual(payload['model'],'local/vision');self.assertEqual(payload['max_tokens'],6000)
                self.assertIn('data:image/jpeg;base64,',payload['messages'][1]['content'][2]['image_url']['url'])
                self.assertNotIn('tools',payload)
            with patch.object(local_ai,'chat',return_value=('{}',{'prompt_tokens':12,'completion_tokens':5})):
                self.assertEqual(app.provider_chat('lmstudio','','local/text','Notes',1100,'http://10.0.0.12:1234/v1')[1],{'input_tokens':12,'output_tokens':5})
        response['choices'][0]['finish_reason']='length'
        with patch.object(local_ai,'request',return_value=response):
            with self.assertRaises(ValueError):local_ai.chat('http://10.0.0.12:1234/v1','','local/text','Notes',1100)


class LocalAnalysis(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='wmb-local-ai-test-',dir=os.environ.get('WMB_TEST_MEDIA_ROOT'));self.root=Path(self.tmp.name)
        (self.root/'password').write_text('synthetic-owner-password');(self.root/'key').write_bytes(b'L'*32)
        self.patches=[patch.object(app,k,v) for k,v in {'DATA':self.root/'data','MEDIA':self.root/'media','AUTH':self.root/'password','CRYPTO_KEY':self.root/'key'}.items()]
        for p in self.patches:p.start()
        app.initialize();stamp=time.time();nonce,cipher=app.encrypt_provider_key('lmstudio','')
        source=app.MEDIA/'sources'/'source';source.write_bytes(b'synthetic-source')
        with app.db() as c:
            c.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('project','Test','gaming','WMB',stamp))
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',('source','project','test.mp4',hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_size,35,0,stamp))
            c.execute('INSERT INTO lmstudio_settings VALUES(1,?,?,?)',('http://10.0.0.12:1234/v1',0,stamp))
            c.execute("INSERT INTO provider_credentials VALUES('lmstudio',?,?,?)",(nonce,cipher,stamp))
            c.execute("INSERT INTO provider_budgets VALUES('lmstudio','',0,0,0,?)",(stamp,))
            for name,vision in [('local/text',0),('local/vision',1)]:
                c.execute("INSERT INTO provider_models VALUES('lmstudio',?,?)",(name,stamp));c.execute('INSERT INTO lmstudio_models VALUES(?,?)',(name,vision))
        app.creative.save_route(dict(feature='analysis',provider='lmstudio',model='local/vision'))
        def frames(args,timeout):
            for i in range(int(args[args.index('-frames:v')+1])):Path(args[-1]%(i+1)).write_bytes(b'synthetic-frame')
            return b''
        self.engine=highlights.HighlightEngine(app.db,app.MEDIA,frames,app.decrypt_provider_key,app.audit)
        self.body=dict(project='project',source='source',interval=1)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def queue(self):
        quote=self.engine.quote(self.body)
        return self.engine.enqueue({**self.body,'quote':quote['quote'],'consent':True,'requestId':'local-scan-0000000001'})['id']

    def test_vision_gate_zero_cost_and_small_batches(self):
        with self.assertRaises(ValueError):app.creative.save_route(dict(feature='analysis',provider='lmstudio',model='local/text'))
        with self.assertRaises(ValueError):app.creative.save_route(dict(feature='artwork',provider='lmstudio',model='local/vision'))
        app.creative.save_route(dict(feature='titles',provider='lmstudio',model='local/text',inputRate=100,outputRate=100,reserveUsd=20))
        quote=self.engine.quote(self.body)
        self.assertTrue(quote['affordable']);self.assertEqual(quote['spec']['upperCostUsd'],0)
        self.assertTrue(quote['spec']['local']);self.assertIn('No cloud API charge',quote['disclosure'])
        self.assertTrue(all(w['frames']<=10 for w in quote['spec']['chunks']))
        with app.db() as c:self.assertEqual(c.execute("SELECT input_rate FROM creative_routes WHERE feature='titles'").fetchone()[0],0)

    def test_completed_local_scan_uses_only_pinned_lan_endpoint(self):
        uid=self.queue()
        with patch.object(local_ai,'chat',return_value=('{"highlights":[]}',{'prompt_tokens':20,'completion_tokens':4})) as request, patch.object(highlights,'vision_request',side_effect=AssertionError('Cloud calls forbidden')):
            while self.engine.tick():pass
            self.assertGreater(request.call_count,1)
            self.assertTrue(all(call.args[0]=='http://10.0.0.12:1234/v1' and call.args[1]=='' for call in request.call_args_list))
        with app.db() as c:
            row=c.execute('SELECT * FROM analyses WHERE id=?',(uid,)).fetchone();usage=c.execute("SELECT * FROM provider_usage WHERE provider='lmstudio'").fetchone()
            self.assertEqual(row['state'],'complete');self.assertEqual(usage['spent_usd'],0);self.assertGreater(usage['requests'],1)

    def test_connection_change_stops_queued_scan_before_sending(self):
        uid=self.queue()
        with app.db() as c:c.execute("UPDATE provider_credentials SET updated=updated+1 WHERE provider='lmstudio'")
        with patch.object(local_ai,'chat') as request:self.engine.tick();request.assert_not_called()
        with app.db() as c:self.assertEqual(c.execute('SELECT state FROM analyses WHERE id=?',(uid,)).fetchone()[0],'failed')

    def test_local_failure_is_not_replayed_or_routed_to_cloud(self):
        uid=self.queue()
        with patch.object(local_ai,'chat',side_effect=ValueError('LM Studio unavailable')) as request,patch.object(highlights,'vision_request',side_effect=AssertionError('Cloud calls forbidden')):
            self.engine.tick();self.engine.tick();request.assert_called_once()
        with app.db() as c:self.assertEqual(c.execute('SELECT state FROM analyses WHERE id=?',(uid,)).fetchone()[0],'failed')


if __name__=='__main__':unittest.main()

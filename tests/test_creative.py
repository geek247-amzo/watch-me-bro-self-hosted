import array
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import app as studio
import creative
import highlights


class CreativeAssets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wmb-creative-test-', dir=os.environ.get('WMB_TEST_MEDIA_ROOT'))
        self.root = Path(self.tmp.name)
        (self.root/'password').write_text('synthetic-only-password')
        (self.root/'key').write_bytes(b'q'*32)
        self.patches = [patch.object(studio, name, value) for name, value in {
            'DATA': self.root/'data', 'MEDIA': self.root/'media', 'AUTH': self.root/'password', 'CRYPTO_KEY': self.root/'key'}.items()]
        for p in self.patches:
            p.start()
        studio.initialize()
        self.engine = studio.creative
        with studio.db() as c:
            c.execute('INSERT INTO projects VALUES(?,?,?,?,?)', ('project','Test','gaming','Watch Me Bro',time.time()))
            c.execute('INSERT INTO projects VALUES(?,?,?,?,?)', ('other','Other','gaming','Watch Me Bro',time.time()))
            for provider, models in {'openai':['gpt-image-1.5','gpt-5'], 'google':['gemini-nano-banana-2.1','lyria-3-clip-preview','gemini-2.5-flash'], 'anthropic':['claude-sonnet-4-5']}.items():
                nonce, cipher = studio.encrypt_provider_key(provider, 'synthetic-key-not-real')
                c.execute('INSERT INTO provider_credentials VALUES(?,?,?,?)', (provider,nonce,cipher,time.time()))
                for model in models:
                    c.execute('INSERT INTO provider_models VALUES(?,?,?)', (provider,model,time.time()))
                c.execute('INSERT INTO provider_budgets VALUES(?,?,?,?,?,?)', (provider,models[-1],1,2,10,time.time()))
        self.route('artwork','openai','gpt-image-1.5')
        self.body = dict(project='project',feature='artwork',prompt='A gaming opening',size='1536x1024',transparent=True,references=[])

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def route(self, feature, provider, model):
        return self.engine.save_route(dict(feature=feature,provider=provider,model=model,reserveUsd=.25,inputRate=1,outputRate=2))

    def picture(self, color='red', alpha=False):
        return studio.run(['ffmpeg','-nostdin','-v','error','-threads','1','-filter_threads','1','-f','lavfi','-i',f'color=c={color}:s=64x64,format=rgba'+(',colorchannelmixer=aa=0.5' if alpha else ''),'-frames:v','1','-threads','1','-c:v','png','-f','image2pipe','pipe:1'])

    def enqueue(self, **overrides):
        body = {**self.body, **overrides}
        quote = self.engine.quote(body)
        return self.engine.enqueue({**body, 'quote':quote['quote'], 'consent':True, 'requestId':'creative-test-0000001'})['id']

    def test_upload_scope_validation_and_alpha(self):
        asset = self.engine.store('project',self.picture(alpha=True),'image','My sticker.png',{'origin':'uploaded'})
        with studio.db() as c:
            row = c.execute('SELECT * FROM assets WHERE id=?',(asset['id'],)).fetchone()
        self.assertEqual(row['alpha'],1)
        self.assertEqual(row['mime'],'image/png')
        self.assertNotIn('synthetic-key', row['provenance'])
        with self.assertRaises(ValueError):
            creative.validate_design({'design':{'intro':asset['id']}}, {})
        with self.assertRaises(ValueError):
            self.engine.store('project',b'<svg>not allowed</svg>','image','bad.svg',{})
        with self.assertRaises(ValueError):
            self.engine.quote({**self.body,'project':'other','references':[asset['id']]})

    def test_generation_requires_consent_idempotency_and_settles_estimate(self):
        with self.assertRaises(ValueError):
            self.engine.enqueue({**self.body,'requestId':'creative-test-0000001'})
        uid = self.enqueue()
        self.assertEqual(self.enqueue(),uid)
        raw = self.picture(alpha=True)
        with patch.object(creative,'generate',return_value=(raw,'image')) as generate:
            self.assertTrue(self.engine.tick())
            self.assertFalse(self.engine.tick())
            generate.assert_called_once()
        with studio.db() as c:
            row = c.execute('SELECT * FROM creative_jobs WHERE id=?',(uid,)).fetchone()
            usage = c.execute("SELECT * FROM provider_usage WHERE provider='openai'").fetchone()
        self.assertEqual(row['state'],'complete')
        self.assertIsNotNone(row['asset'])
        self.assertAlmostEqual(usage['spent_usd'],.25)
        self.assertEqual(usage['reserved_usd'],0)

    def test_ambiguous_failure_holds_reserve_and_restart_never_replays(self):
        uid = self.enqueue()
        with patch.object(creative,'generate',side_effect=ValueError('Provider unavailable')) as generate:
            self.engine.tick();self.engine.tick();generate.assert_called_once()
        with studio.db() as c:
            self.assertEqual(c.execute("SELECT reserved_usd FROM provider_usage WHERE provider='openai'").fetchone()[0],.25)
            c.execute("UPDATE creative_jobs SET state='running' WHERE id=?",(uid,))
        self.engine.initialize()
        with studio.db() as c:
            self.assertEqual(c.execute('SELECT state FROM creative_jobs WHERE id=?',(uid,)).fetchone()[0],'interrupted')
        self.assertFalse(self.engine.tick())

    def test_changed_settings_refund_unsent_and_caps_hold(self):
        uid = self.enqueue()
        self.route('artwork','google','gemini-nano-banana-2.1')
        with patch.object(creative,'generate') as generate:
            self.engine.tick();generate.assert_not_called()
        with studio.db() as c:
            self.assertEqual(c.execute("SELECT reserved_usd FROM provider_usage WHERE provider='openai'").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT state FROM creative_jobs WHERE id=?',(uid,)).fetchone()[0],'failed')
            c.execute("UPDATE provider_budgets SET monthly_cap_usd=.1 WHERE provider='google'")
        with self.assertRaises(ValueError):
            self.engine.enqueue({**self.body,'transparent':False,'requestId':'creative-test-0000002','quote':self.engine.quote({**self.body,'transparent':False})['quote'],'consent':True})

    def test_capability_routing_and_transparency_restrictions(self):
        with self.assertRaises(ValueError):
            self.route('artwork','anthropic','claude-sonnet-4-5')
        self.route('music','google','lyria-3-clip-preview')
        self.assertEqual(self.engine.quote({**self.body,'feature':'music','transparent':False})['spec']['model'],'lyria-3-clip-preview')
        self.route('artwork','google','gemini-nano-banana-2.1')
        with self.assertRaises(ValueError):
            self.engine.quote(self.body)
        self.route('analysis','anthropic','claude-sonnet-4-5')
        with studio.db() as c:
            self.assertEqual(highlights.analysis_budget(c,'anthropic')['model'],'claude-sonnet-4-5')

    def test_shared_cap_is_rechecked_at_admission(self):
        with studio.db() as c:
            c.execute("UPDATE provider_budgets SET monthly_cap_usd=.3 WHERE provider='openai'")
        body = self.body
        quote = self.engine.quote(body)
        self.engine.enqueue({**body,'requestId':'creative-test-0000001','quote':quote['quote'],'consent':True})
        with self.assertRaises(ValueError):
            self.engine.enqueue({**body,'requestId':'creative-test-0000002','quote':quote['quote'],'consent':True})
        with studio.db() as c:
            self.assertAlmostEqual(c.execute("SELECT reserved_usd FROM provider_usage WHERE provider='openai'").fetchone()[0],.25)

    def test_official_artwork_and_music_payloads(self):
        path = self.root/'reference.png';path.write_bytes(self.picture())
        spec = self.engine.quote(self.body)['spec']
        response = {'data':[{'b64_json':base64.b64encode(b'fake-image').decode()}]}
        with patch.object(creative,'request_json',return_value=response) as request:
            raw, kind = creative.generate(spec,'synthetic-key',[path])
            args = request.call_args.args
            self.assertEqual(args[0],'https://api.openai.com/v1/images/edits')
            self.assertEqual(args[2]['background'],'transparent')
            self.assertTrue(args[2]['images'][0]['image_url'].startswith('data:image/png;base64,'))
            self.assertEqual(raw,b'fake-image')
        response = {'steps':[{'type':'model_output','content':[{'type':'audio','data':base64.b64encode(b'fake-music').decode()}]}]}
        with patch.object(creative,'request_json',return_value=response) as request:
            raw, kind = creative.generate({**spec,'feature':'music','provider':'google','model':'lyria-3-clip-preview'},'synthetic-key',[])
            self.assertEqual(request.call_args.args[0],'https://generativelanguage.googleapis.com/v1beta/interactions')
            self.assertIn('No vocals',request.call_args.args[2]['input'])
            self.assertEqual((raw,kind),(b'fake-music','audio'))
        response = {'steps':[{'type':'model_output','content':[{'type':'image','data':base64.b64encode(b'fake-image').decode()}]}]}
        with patch.object(creative,'request_json',return_value=response) as request:
            creative.generate({**spec,'provider':'google','model':'gemini-nano-banana-2.1'},'synthetic-key',[path])
            self.assertEqual(request.call_args.args[2]['response_format']['aspect_ratio'],'3:2')

    def test_non_openai_vision_payloads_and_usage(self):
        path = self.root/'frame.jpg';path.write_bytes(b'synthetic-frame')
        response = {'stop_reason':'end_turn','content':[{'type':'text','text':'{"highlights":[]}'}],'usage':{'input_tokens':20,'output_tokens':4}}
        with patch.object(creative,'request_json',return_value=response) as request:
            output, usage = creative.vision_request('anthropic','synthetic-key','claude-sonnet-4-5','Return evidence',[(2,path)])
            self.assertEqual(usage,{'prompt_tokens':20,'completion_tokens':4})
            self.assertEqual(request.call_args.args[2]['messages'][0]['content'][0]['text'],'SOURCE TIMESTAMP 2')
        response = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"highlights":[]}'}]}}],'usageMetadata':{'promptTokenCount':21,'candidatesTokenCount':4,'thoughtsTokenCount':2}}
        with patch.object(creative,'request_json',return_value=response):
            output, usage = creative.vision_request('google','synthetic-key','gemini-2.5-flash','Return evidence',[(2,path)])
            self.assertEqual(usage,{'prompt_tokens':21,'completion_tokens':6})

    def test_assigned_gemini_and_anthropic_scans_use_their_own_ledger(self):
        source = studio.MEDIA/'sources'/'mock-source';source.write_bytes(b'synthetic-frames-source')
        with studio.db() as c:
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',('mock-source','project','mock.mp4',hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_size,4,0,time.time()))
        def frames(args,timeout):
            for i in range(int(args[args.index('-frames:v')+1])):
                Path(args[-1]%(i+1)).write_bytes(b'synthetic-frame')
            return b''
        engine = highlights.HighlightEngine(studio.db,studio.MEDIA,frames,studio.decrypt_provider_key,studio.audit)
        for provider, model in [('google','gemini-2.5-flash'),('anthropic','claude-sonnet-4-5')]:
            self.route('analysis',provider,model)
            body = dict(project='project',source='mock-source',interval=1)
            quote = engine.quote(body)
            self.assertEqual(quote['spec']['provider'],provider)
            uid = engine.enqueue({**body,'quote':quote['quote'],'consent':True,'requestId':'scan-'+provider+'-00000000000001'})['id']
            with patch.object(highlights,'creative_vision_request',return_value=('{"highlights":[]}',{'prompt_tokens':20,'completion_tokens':4})) as request:
                engine.tick();self.assertEqual(request.call_args.args[0],provider)
            with studio.db() as c:
                self.assertEqual(c.execute('SELECT state FROM analyses WHERE id=?',(uid,)).fetchone()[0],'complete')
                usage = c.execute('SELECT * FROM provider_usage WHERE provider=?',(provider,)).fetchone()
                self.assertGreater(usage['spent_usd'],0)
                self.assertEqual(usage['reserved_usd'],0)

    def test_actual_render_with_artwork_alpha_and_music_scopes(self):
        source = studio.MEDIA/'sources'/'source'
        studio.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-f','lavfi','-i','color=c=blue:s=160x90:r=30:d=2','-an','-c:v','libx264','-threads','1','-f','mp4',str(source)])
        image = self.engine.store('project',self.picture('red',True),'image','Sticker',{})['id']
        background = self.engine.store('project',self.picture('green'),'image','Background',{})['id']
        music_raw = studio.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-c:a','pcm_s16le','-f','wav','pipe:1'])
        music = self.engine.store('project',music_raw,'audio','Music',{})['id']
        with source.open('rb') as f:
            sha = hashlib.file_digest(f,'sha256').hexdigest()
        with studio.db() as c:
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',('source','project','source.mp4',sha,source.stat().st_size,2,0,time.time()))
        plan = dict(title='Styled test',format='landscape',resolution='720p',audio='mute',cuts=[dict(source='source',start=0,end=1)],captions=[],overlay=dict(intro='Hello',intro_seconds=2,cta='Subscribe',outro_seconds=3),
                    design=dict(intro=background,outro=background,overlay=image,music=music,music_volume=.6,music_scope='cards',position='top-left',overlay_size=.25))
        job = dict(id='styled-test',project='project',body=json.dumps(plan))
        video = Path(studio.render(job))
        self.assertTrue(video.is_file())
        meta = json.loads(studio.run(['ffprobe','-v','error','-show_format','-of','json',str(video)]))
        self.assertAlmostEqual(float(meta['format']['duration']),6,delta=.15)
        def pixel(t,x,y):
            return studio.run(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(t),'-i',str(video),'-vf',f'crop=2:2:{x}:{y},format=rgb24','-frames:v','1','-threads','1','-f','rawvideo','pipe:1'])[:3]
        self.assertGreater(pixel(.5,640,50)[1],80,'Opening background must be green')
        rgba = pixel(2.5,50,50)
        self.assertGreater(rgba[0],70,'Half-alpha red sticker must be visible')
        self.assertGreater(rgba[2],70,'Blue gameplay must remain visible through alpha')
        self.assertGreater(pixel(4,640,50)[1],80,'Ending background must be green')
        def rms(t):
            samples = array.array('f',studio.run(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(t),'-i',str(video),'-t','0.2','-vn','-f','f32le','-ac','1','pipe:1']))
            return math.sqrt(sum(x*x for x in samples)/len(samples))
        self.assertGreater(rms(1),.01,'Music must play on cards')
        self.assertLess(rms(2.4),.001,'Cards-only music must be silent during muted gameplay')
        manifest = json.loads((video.parent/'manifest.json').read_text())
        self.assertEqual(len(manifest['assets']),3)


if __name__ == '__main__':
    unittest.main()

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import app as studio
import highlights as visual


class EvidenceValidation(unittest.TestCase):
    def moment(self):
        return dict(start=1, end=9, event_time=5, score=88, title='Visible test play', reason='A visible test event',
                    category='skill', hook='Watch this play', cta='Subscribe to WatchMeBro',
                    evidence=[dict(timestamp=5, observation='The player reaches the target')])

    def test_unseen_frames_and_nonfinite_timestamps_are_rejected(self):
        window = dict(start=0, end=10, coreStart=0, coreEnd=10)
        for mutate in [lambda h: h.update(event_time=float('nan')),
                       lambda h: h.update(end=11),
                       lambda h: h.update(evidence=[dict(timestamp=5.5, observation='Not inspected')])]:
            h = self.moment(); mutate(h)
            with self.assertRaises(ValueError):
                visual.clean_moments({'highlights': [h]}, window, [1, 5, 8])
        self.assertEqual(len(visual.clean_moments({'highlights': [self.moment()]}, window, [1, 5, 8])), 1)

    def test_overlap_covers_whole_timeline_and_duplicates_merge(self):
        windows = visual.windows(4, 134, 1)
        self.assertEqual([(w['coreStart'], w['coreEnd']) for w in windows], [(4,64), (64,124), (124,134)])
        self.assertLess(windows[1]['start'], windows[0]['end'])
        a = self.moment(); b = {**a, 'score': 90, 'start': 2}
        self.assertEqual(visual.deduplicate([a,b]), [b])
        self.assertEqual(visual.clean_moments({'highlights': []}, windows[0], []), [])

    def test_vision_request_uses_images_fixed_host_and_reasoning_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'test.jpg'; image.write_bytes(b'test-image-not-private-footage')
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): pass
                def read(self, _): return b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"highlights\\":[]}"}}],"usage":{"prompt_tokens":20,"completion_tokens":10}}'
            class Opener:
                def open(self, request, timeout):
                    self.request = request
                    return Response()
            opener = Opener()
            with patch.object(visual.urllib.request, 'build_opener', return_value=opener):
                result, usage = visual.vision_request('synthetic-key', 'gpt-5', 'Find visible test events', [(3, image)])
            payload = json.loads(opener.request.data)
            self.assertEqual(opener.request.full_url, 'https://api.openai.com/v1/chat/completions')
            self.assertNotIn('synthetic-key', opener.request.full_url)
            self.assertEqual(payload['reasoning_effort'], 'low')
            self.assertNotIn('temperature', payload)
            self.assertNotIn('max_tokens', payload)
            self.assertEqual(payload['max_completion_tokens'], 6000)
            self.assertFalse(payload['store'])
            self.assertTrue(payload['messages'][1]['content'][2]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(json.loads(result), {'highlights': []})
            self.assertEqual(usage['prompt_tokens'], 20)
            self.assertIsNone(visual.RejectRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid.example'))


class AnalysisEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wmb-analysis-test-', dir=os.environ.get('WMB_TEST_MEDIA_ROOT'))
        self.root = Path(self.tmp.name)
        (self.root/'password').write_text('synthetic-test-password')
        (self.root/'key').write_bytes(b'z'*32)
        self.patches = [patch.object(studio, name, value) for name, value in {
            'DATA': self.root/'data', 'MEDIA': self.root/'media', 'AUTH': self.root/'password', 'CRYPTO_KEY': self.root/'key'}.items()]
        for p in self.patches: p.start()
        self.engine = visual.HighlightEngine(studio.db, studio.MEDIA, self.fake_extract, studio.decrypt_provider_key, studio.audit)
        self.engine_patch = patch.object(studio, 'highlights', self.engine); self.engine_patch.start()
        studio.initialize()
        source = studio.MEDIA/'sources'/'abc'; source.write_bytes(b'synthetic-original')
        nonce, cipher = studio.encrypt_provider_key('openai', 'synthetic-openai-key')
        with studio.db() as c:
            c.execute('INSERT INTO projects VALUES(?,?,?,?,?)', ('project','Test','gaming','Watch Me Bro',time.time()))
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)', ('abc','project','test.mp4',hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_size,130,1,time.time()))
            c.execute('INSERT INTO provider_credentials VALUES(?,?,?,?)', ('openai',nonce,cipher,time.time()))
            c.execute('INSERT INTO provider_models VALUES(?,?,?)', ('openai','gpt-5',time.time()))
            c.execute('INSERT INTO provider_budgets VALUES(?,?,?,?,?,?)', ('openai','gpt-5',1.25,10,10,time.time()))
        self.body = dict(project='project', source='abc', game='Test game', interval=1)

    def tearDown(self):
        self.engine_patch.stop()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def fake_extract(self, args, timeout):
        for i in range(int(args[args.index('-frames:v')+1])):
            Path(args[-1] % (i+1)).write_bytes(b'synthetic-jpeg')
        return b''

    def queue(self, **overrides):
        body = {**self.body, **overrides}
        quote = self.engine.quote(body)
        request = {**body, 'quote': quote['quote'], 'consent': True, 'requestId': 'synthetic-request-1234'}
        result = self.engine.enqueue(request)
        return result['id'], request

    def row(self, uid):
        with studio.db() as c:
            return dict(c.execute('SELECT * FROM analyses WHERE id=?', (uid,)).fetchone())

    def usage(self):
        with studio.db() as c:
            return dict(c.execute("SELECT * FROM provider_usage WHERE provider='openai'").fetchone())

    @staticmethod
    def response(key, model, prompt, frames):
        body = json.loads(prompt); start, end = body['core_range']
        timestamp = next(t for t, _ in frames if t >= start)
        highlight = dict(start=start, end=min(end, start+3), event_time=start+1,
                         title='A visible synthetic play', reason='The sampled target is visible', category='skill', score=85,
                         hook='Watch the target', cta='Subscribe for more gameplay',
                         evidence=[dict(timestamp=timestamp, observation='The target appears in this frame')])
        return json.dumps({'highlights':[highlight]}), dict(prompt_tokens=100, completion_tokens=100)

    def test_consent_budget_idempotency_and_queued_cancellation(self):
        quote = self.engine.quote(self.body)
        with self.assertRaises(ValueError):
            self.engine.enqueue({**self.body, 'quote':quote['quote'], 'requestId':'synthetic-request-1234'})
        uid, request = self.queue()
        self.assertGreater(self.usage()['reserved_usd'], 0)
        self.assertTrue(self.engine.enqueue(request)['duplicate'])
        with patch.object(visual, 'vision_request') as provider:
            self.engine.cancel(uid)
            self.assertFalse(self.engine.tick())
            provider.assert_not_called()
        self.assertEqual(self.row(uid)['state'], 'cancelled')
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)
        self.assertEqual(self.usage()['requests'], 0)

    def test_gpt5_quick_scan_cost_uses_model_appropriate_image_allowance(self):
        with studio.db() as c:
            c.execute('UPDATE sources SET duration=1462.027')
        quote = self.engine.quote({**self.body, 'interval': 2})
        self.assertTrue(quote['affordable'])
        self.assertEqual(quote['frameCount'], 852)
        self.assertEqual(quote['spec']['frameTokenReserve'], 1024)
        self.assertAlmostEqual(quote['spec']['upperCostUsd'], 2.84656)
        self.assertEqual(visual.frame_token_reserve('gpt-5-mini'), 4096)

    def test_successful_scan_persists_partial_and_final_results_and_settles(self):
        uid, _ = self.queue()
        with patch.object(visual, 'vision_request', side_effect=self.response) as provider:
            self.assertTrue(self.engine.tick())
            partial = self.row(uid)
            self.assertEqual(partial['completed'], 1)
            self.assertEqual(partial['state'], 'queued')
            self.assertEqual(len(json.loads(partial['results'])), 1)
            self.assertTrue(self.engine.tick()); self.assertTrue(self.engine.tick())
            self.assertEqual(provider.call_count, 3)
        final = self.row(uid)
        self.assertEqual(final['state'], 'complete')
        self.assertEqual(len(json.loads(final['results'])), 3)
        self.assertEqual(final['completed'], final['total'])
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)
        self.assertAlmostEqual(self.usage()['spent_usd'], 3*(100*1.25+100*10)/1e6)
        self.assertEqual(list((studio.MEDIA/'analysis-tmp').iterdir()), [])

    def test_ambiguous_request_holds_only_current_reserve_and_does_not_retry(self):
        uid, _ = self.queue()
        first = json.loads(self.row(uid)['spec'])['chunks'][0]['estimate']
        with patch.object(visual, 'vision_request', side_effect=TimeoutError) as provider:
            self.engine.tick()
            self.assertFalse(self.engine.tick())
            provider.assert_called_once()
        self.assertEqual(self.row(uid)['state'], 'failed')
        self.assertAlmostEqual(self.usage()['reserved_usd'], first)

    def test_restart_refunds_unsent_work_without_reissuing_paid_request(self):
        uid, _ = self.queue()
        with studio.db() as c:
            c.execute("UPDATE analyses SET state='running',in_flight_usd=.05 WHERE id=?", (uid,))
        self.engine.recover()
        self.assertEqual(self.row(uid)['state'], 'interrupted')
        self.assertAlmostEqual(self.usage()['reserved_usd'], .05)
        self.assertFalse(self.engine.tick())

    def test_unseen_evidence_is_skipped_without_stopping_the_scan(self):
        uid, _ = self.queue()
        def invalid(*args):
            output, usage = self.response(*args)
            parsed = json.loads(output); parsed['highlights'][0]['evidence'][0]['timestamp'] = .123
            return json.dumps(parsed), usage
        with patch.object(visual, 'vision_request', side_effect=invalid):
            self.engine.tick(); self.engine.tick(); self.engine.tick()
        self.assertEqual(self.row(uid)['state'], 'complete')
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)
        self.assertGreater(self.usage()['spent_usd'], 0)
        self.assertEqual(json.loads(self.row(uid)['results']), [])
        with studio.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE action='analysis.candidate-rejected' AND object=?",(uid,)).fetchone()[0],3)

    def test_out_of_window_pick_does_not_discard_valid_picks_or_later_windows(self):
        uid, _ = self.queue()
        def mixed(*args):
            output, usage = self.response(*args)
            parsed = json.loads(output)
            parsed['highlights'].append({**parsed['highlights'][0],'end':9999})
            return json.dumps(parsed),usage
        with patch.object(visual,'vision_request',side_effect=mixed) as provider:
            for _ in range(3): self.engine.tick()
        self.assertEqual(provider.call_count,3)
        self.assertEqual(self.row(uid)['state'],'complete')
        self.assertEqual(len(json.loads(self.row(uid)['results'])),3)
        self.assertEqual(self.row(uid)['completed'],3)
        self.assertAlmostEqual(self.usage()['reserved_usd'],0)

    def test_budget_changes_and_source_changes_stop_before_provider_call(self):
        uid, _ = self.queue()
        with studio.db() as c:
            c.execute('UPDATE provider_budgets SET monthly_cap_usd=.00001')
        with patch.object(visual, 'vision_request') as provider:
            self.engine.tick(); provider.assert_not_called()
        self.assertEqual(self.row(uid)['state'], 'failed')
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)

    def test_modified_original_is_rejected_before_provider_call(self):
        uid, _ = self.queue()
        (studio.MEDIA/'sources'/'abc').write_bytes(b'changed-source')
        with patch.object(visual, 'vision_request') as provider:
            self.engine.tick(); provider.assert_not_called()
        self.assertEqual(self.row(uid)['state'], 'failed')
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)

    def test_cancellation_during_call_keeps_results_and_refunds_unsent_sections(self):
        uid, _ = self.queue()
        def response(*args):
            self.engine.cancel(uid)
            return self.response(*args)
        with patch.object(visual, 'vision_request', side_effect=response) as provider:
            self.engine.tick()
            self.assertFalse(self.engine.tick())
            provider.assert_called_once()
        self.assertEqual(self.row(uid)['state'], 'cancelled')
        self.assertEqual(len(json.loads(self.row(uid)['results'])), 1)
        self.assertAlmostEqual(self.usage()['reserved_usd'], 0)
        self.assertGreater(self.usage()['spent_usd'], 0)

    def test_real_frame_extraction_feeds_timestamps_to_mocked_vision(self):
        source = studio.MEDIA/'sources'/'abc'
        subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15',
                        '-t','3','-c:v','libx264','-threads','1','-f','mp4',str(source)],check=True)
        with studio.db() as c:
            c.execute('UPDATE sources SET sha256=?,bytes=?,duration=3', (hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_size))
        uid, _ = self.queue()
        self.engine.run = studio.run
        def inspect(key, model, prompt, frames):
            self.assertGreaterEqual(len(frames), 2)
            self.assertTrue(all(path.read_bytes().startswith(b'\xff\xd8') for _,path in frames))
            return self.response(key,model,prompt,frames)
        with patch.object(visual,'vision_request',side_effect=inspect):
            self.engine.tick()
        self.assertEqual(self.row(uid)['state'], 'complete', self.row(uid)['error'])

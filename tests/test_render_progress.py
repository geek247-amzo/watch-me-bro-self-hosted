from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

import app
import render_progress as rp


class RenderProgress(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='wmb-progress-')
        self.data=Path(self.tmp.name)
        self.plan=dict(format='landscape',resolution='720p',audio='mute',cuts=[dict(source='s',start=0,end=100)],captions=[],overlay={},design={})
        self.job=dict(id='current',state='running',body=json.dumps(self.plan),created=900,started=980,elapsed=None)
        with self.db() as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,state TEXT,body TEXT,created REAL,started REAL,elapsed REAL)')
            c.executescript(rp.SCHEMA)
            c.execute('INSERT INTO jobs VALUES(:id,:state,:body,:created,:started,:elapsed)',self.job)

    def tearDown(self):
        self.tmp.cleanup()

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.data/'test.sqlite');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def saved(self,processed=10,modified=1000):
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO render_progress VALUES(?,?)',('current',json.dumps(dict(stages=rp.stages(self.plan),index=1,started=980))))
        path=self.data/'render-progress/current-1.stats';path.parent.mkdir(exist_ok=True)
        path.write_text(f'out_time_us={round(processed*1e6)}\nprogress=continue\n')
        os.utime(path,(modified,modified))
        return path

    def history(self,plan=None):
        plan=plan or self.plan
        with self.db() as c:
            c.execute("INSERT INTO jobs VALUES('history','review',?,800,800,500)",(json.dumps(plan),))
            for i,step in enumerate(rp.stages(plan)):
                c.execute('INSERT INTO render_steps VALUES(?,?,?,?,?,?)',('history',i,step['kind'],rp.profile(plan),step['units'],step['units']*2))

    def view(self,job=None,now=1000):
        with self.db() as c:
            return rp.snapshot(c,job or self.job,self.data,now=now)

    def test_cold_start_current_speed_and_no_clock_only_percent(self):
        self.saved()
        first=self.view()
        self.assertEqual(first['percent'],10)
        self.assertAlmostEqual(first['stageEtaSeconds'],180)
        self.assertIsNone(first['etaSeconds'])
        self.assertIn('not yet calibrated',first['estimateBasis'])
        later=self.view(now=1020)
        self.assertEqual(later['percent'],10)
        self.assertGreater(later['stageEtaSeconds'],first['stageEtaSeconds'])

    def test_full_estimate_uses_matching_work_history_and_length(self):
        self.history();self.saved()
        first=self.view()
        self.assertAlmostEqual(first['etaSeconds'],180+200+2+2)
        queued=dict(self.job,state='queued',started=None)
        q=self.view(queued)
        self.assertFalse(q['queueWaitIncluded'])
        self.assertEqual(q['queueAhead'],0)
        longer=dict(self.plan,cuts=[dict(source='s',start=0,end=200)])
        q2=self.view(dict(queued,body=json.dumps(longer)))
        self.assertGreater(q2['etaSeconds'],q['etaSeconds'])
        self.assertIsNone(self.view(dict(queued,body=json.dumps(dict(self.plan,resolution='1080p'))))['etaSeconds'])

    def test_stale_and_finishing_do_not_claim_zero_or_completion(self):
        self.history();self.saved()
        stale=self.view(now=1200)
        self.assertTrue(stale['stale']);self.assertIsNone(stale['etaSeconds']);self.assertIsNone(stale['stageEtaSeconds'])
        self.saved(processed=100)
        finishing=self.view()
        self.assertEqual(finishing['percent'],99);self.assertIsNone(finishing['etaSeconds'])
        self.assertIn('finishing',finishing['estimateBasis'])
        self.assertEqual(self.view(dict(self.job,state='review'))['percent'],100)
        self.assertIsNone(self.view(dict(self.job,state='failed'))['percent'])

    def test_missing_and_partial_progress_is_unknown_and_bounded(self):
        self.assertIsNone(self.view()['percent'])
        path=self.saved();path.write_text('out_time_us=not-a-number\nprogress=continue\nout_time_us=')
        self.assertIsNone(rp.read_encoder(path)[0])
        self.assertIsNone(self.view()['percent'])
        path.write_text('x'*20000+'\nout_time_us=5000000\n')
        self.assertEqual(rp.read_encoder(path)[0],5)

    def test_steps_match_optional_render_passes(self):
        self.assertEqual([s['kind'] for s in rp.stages(self.plan)],['verify','clip','content-copy','thumbnail','save'])
        styled=dict(self.plan,captions=[dict(start=0,end=1,text='Caption')],overlay=dict(intro='Opening',intro_seconds=2,cta='Subscribe',outro_seconds=3),design=dict(intro='picture',music='music'))
        steps=rp.stages(styled)
        self.assertEqual([s['kind'] for s in steps],['verify','clip','captions','card','card','join','artwork','titles','thumbnail','save'])
        self.assertEqual(next(s['mediaSeconds'] for s in steps if s['kind']=='titles'),105)

    def test_restart_clears_old_measurements_and_content_delete_cascades(self):
        self.saved()
        with self.db() as c:
            c.execute('INSERT INTO render_steps VALUES(?,?,?,?,?,?)',('current',1,'clip',rp.profile(self.plan),100,20))
        tracker=rp.Tracker(self.db,self.data,self.job,self.plan,{}, {},app.run)
        with self.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM render_steps').fetchone()[0],0)
            self.assertEqual(json.loads(c.execute('SELECT body FROM render_progress').fetchone()[0])['index'],0)
            c.execute("DELETE FROM jobs WHERE id='current'")
            self.assertEqual(c.execute('SELECT count(*) FROM render_progress').fetchone()[0],0)

    def test_real_ffmpeg_reports_processed_media_and_records_timing(self):
        plan=dict(self.plan,cuts=[dict(source='s',start=0,end=2)])
        with self.db() as c:
            c.execute('UPDATE jobs SET body=?',(json.dumps(plan),))
        tracker=rp.Tracker(self.db,self.data,self.job,plan,{}, {},app.run);tracker.finish()
        errors=[]
        def encode():
            try:
                tracker.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-re','-f','lavfi','-i','color=c=blue:s=160x90:r=30:d=2','-an','-c:v','libx264','-tune','zerolatency','-threads','1',str(self.data/'video.mp4')])
            except Exception as error:
                errors.append(type(error).__name__)
        thread=threading.Thread(target=encode);thread.start()
        observed=[]
        for _ in range(65):
            value,_=rp.read_encoder(self.data/'render-progress/current-1.stats')
            if value is not None:observed.append(value)
            if not thread.is_alive():break
            time.sleep(.05)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertTrue(any(value>0 for value in observed))
        with self.db() as c:
            record=c.execute("SELECT * FROM render_steps WHERE kind='clip'").fetchone()
            self.assertEqual(record['units'],2);self.assertGreater(record['wall_seconds'],1)


if __name__=='__main__':unittest.main()

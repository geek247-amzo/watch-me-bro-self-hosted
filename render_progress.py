"""Measured render steps and deliberately uncertain, local-only time estimates."""
import json
import math
from pathlib import Path
import re
import statistics
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS render_progress(
 job TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS render_steps(
 job TEXT REFERENCES jobs(id) ON DELETE CASCADE, step INTEGER, kind TEXT,
 profile TEXT, units REAL, wall_seconds REAL, PRIMARY KEY(job,step));
'''


def stages(plan, sources=None, assets=None):
    sources, assets = sources or {}, assets or {}
    design, overlay = plan.get('design', {}), plan.get('overlay', {})
    gameplay = sum(c['end']-c['start'] for c in plan['cuts'])
    intro = overlay.get('intro_seconds', 3) if overlay.get('intro') or design.get('intro') else 0
    outro = overlay.get('outro_seconds', 5) if overlay.get('cta') or design.get('outro') else 0
    total = intro+gameplay+outro
    selected = {c['source'] for c in plan['cuts']}
    asset_ids = {design.get(k) for k in ['intro', 'outro', 'overlay', 'music']} - {None, ''}
    verify_bytes = sum(sources.get(uid, {}).get('bytes', 0) for uid in selected) + sum(assets.get(uid, {}).get('bytes', 0) for uid in asset_ids)
    result = [dict(kind='verify', label='Checking original files and artwork', units=max(1, verify_bytes), mediaSeconds=0)]
    def add(kind, label, duration=0):
        result.append(dict(kind=kind, label=label, units=max(1e-6, duration) if duration else 1, mediaSeconds=duration))
    for i, cut in enumerate(plan['cuts'], 1):
        add('clip', f'Preparing clip {i} of {len(plan["cuts"])}', cut['end']-cut['start'])
    add('captions' if plan.get('captions') else 'content-copy', 'Adding captions' if plan.get('captions') else 'Joining chosen clips', gameplay)
    if outro:
        add('card', 'Making the ending screen', outro)
    if intro:
        add('card', 'Making the opening screen', intro)
    if intro or outro:
        add('join', 'Joining gameplay and cards', total)
    if asset_ids:
        add('artwork', 'Adding pictures and music', total)
    if intro or outro or overlay.get('headline'):
        add('titles', 'Adding titles and 3D lettering', total)
    add('thumbnail', 'Making the cover picture')
    add('save', 'Saving video details and finishing checks')
    return result


def profile(plan):
    d, o = plan.get('design', {}), plan.get('overlay', {})
    return json.dumps([2, plan.get('resolution', '720p'), plan['format'], plan['audio'],
                       bool(plan.get('captions')), [bool(d.get(k)) for k in ['intro', 'outro', 'overlay', 'music']],
                       o.get('title_style', '3d')], separators=(',', ':'))


def rates(conn, key, job=None):
    rows = conn.execute('''SELECT r.kind,r.units,r.wall_seconds FROM render_steps r
        JOIN jobs j ON j.id=r.job WHERE r.profile=? AND
        (j.state IN ('review','approved') OR r.job=?)
        ORDER BY j.created DESC,r.step DESC LIMIT 160''', (key, job)).fetchall()
    samples = {}
    for row in rows:
        if row['units'] > 0 and row['wall_seconds'] > 0:
            samples.setdefault(row['kind'], []).append(row['wall_seconds']/row['units'])
    return {kind: statistics.median(values[:20]) for kind, values in samples.items()}


def remaining_estimate(items, measured):
    if any(item['kind'] not in measured for item in items):
        return None
    return sum(item['units']*measured[item['kind']] for item in items)


def read_encoder(path):
    """Read only the bounded tail; incomplete progress records are normal."""
    try:
        with path.open('rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell()-16384))
            lines = f.read(16384).decode('ascii', errors='ignore').splitlines()
        values = [float(line.split('=', 1)[1])/1e6 for line in lines if re.fullmatch(r'out_time_us=-?\d+', line)]
        value = max(0, values[-1]) if values and math.isfinite(values[-1]) else None
        return value, path.stat().st_mtime
    except (OSError, ValueError):
        return None, None


def snapshot(conn, job, data, sources=None, assets=None, now=None):
    now = time.time() if now is None else now
    state = job['state']
    base = dict(stage='Waiting its turn', percent=None, stageIndex=0, stageCount=0,
                elapsedSeconds=max(0, now-job['started']) if job.get('started') and state=='running' else job.get('elapsed'),
                etaSeconds=None, stageEtaSeconds=None, estimateBasis='Not enough measured data yet.',
                updated=now, reportAgeSeconds=None, stale=False, queueWaitIncluded=False)
    if state in ('review', 'approved'):
        return dict(base, stage='Finished', percent=100, estimateBasis='Completed successfully.')
    if state == 'failed':
        return dict(base, stage='Stopped — check the error above', estimateBasis='No completion estimate for a failed job.')
    plan = json.loads(job['body'])
    items = stages(plan, sources, assets)
    base['stageCount'] = len(items)
    measured = rates(conn, profile(plan), job['id'] if state=='running' else None)
    if state == 'queued':
        eta = remaining_estimate(items, measured)
        ahead = conn.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running') AND (state='running' OR created<?) AND id!=?", (job['created'], job['id'])).fetchone()[0]
        return dict(base, queueAhead=ahead, etaSeconds=eta,
                    estimateBasis='Previous matching render steps; queue waiting time is unknown.' if eta is not None else 'Waiting time and processing estimate are not known yet.')
    row = conn.execute('SELECT body FROM render_progress WHERE job=?', (job['id'],)).fetchone()
    if not row:
        return dict(base, stage='Preparing render', estimateBasis='This render has not reported a measured step yet.')
    saved = json.loads(row['body'])
    index = saved['index']
    if index >= len(saved['stages']):
        return dict(base, stage='Finishing checks', stageIndex=len(items), estimateBasis='Waiting for successful completion; remaining time is not known.')
    current = saved['stages'][index]
    base.update(stage=current['label'], stageIndex=index+1, stageCount=len(saved['stages']))
    processed, modified = read_encoder(Path(data)/'render-progress'/f'{job["id"]}-{index}.stats')
    age = max(0, now-modified) if modified is not None else max(0, now-saved['started'])
    duration = current['mediaSeconds']
    base.update(reportAgeSeconds=age if duration else None, stale=bool(duration and age>90))
    elapsed = max(0, now-saved['started'])
    current_eta = None
    if processed is not None and duration > 0:
        processed = min(duration, processed)
        base['percent'] = min(99, int(100*processed/duration))
        base.update(processedSeconds=processed, stepDurationSeconds=duration)
        if not base['stale'] and elapsed >= 5 and .5 <= processed < duration*.995:
            current_eta = elapsed/processed*(duration-processed)
            base['estimateBasis'] = 'Actual speed in this step plus measured matching steps; approximate, not a deadline.'
        elif processed >= duration*.995:
            base['estimateBasis'] = 'Encoder is finishing this step; remaining time is not known.'
    if base['stale']:
        base['estimateBasis'] = 'No recent encoder report. The process may still be working; remaining time is unknown.'
    elif current_eta is None and processed is None and current['kind'] in measured:
        # History is a forecast, never a fake percent or a ticking countdown.
        expected = current['units']*measured[current['kind']]
        if elapsed < expected:
            current_eta = expected-elapsed
            base['estimateBasis'] = 'Previous matching render steps; approximate, not a deadline.'
    later = remaining_estimate(saved['stages'][index+1:], measured)
    base['stageEtaSeconds'] = current_eta
    if current_eta is not None and later is not None:
        base['etaSeconds'] = current_eta+later
    elif current_eta is not None:
        base['estimateBasis'] = 'Actual/observed step speed. Later steps are not yet calibrated; total remaining time is unknown.'
    return base


class Tracker:
    def __init__(self, db, data, job, plan, sources, assets, run):
        self.db, self.data, self.uid, self.plan, self.execute = db, Path(data), job['id'], plan, run
        self.items, self.index = stages(plan, sources, assets), 0
        with db() as c:
            self.enabled = c.execute('SELECT 1 FROM jobs WHERE id=?', (self.uid,)).fetchone() is not None
            if self.enabled:
                c.execute('DELETE FROM render_steps WHERE job=?', (self.uid,))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', self.uid):
            raise ValueError('Invalid render identifier.')
        self.path = self.data/'render-progress'/f'{self.uid}-0.stats'
        if self.enabled:
            self.path.parent.mkdir(mode=0o700, exist_ok=True)
            self.begin()

    def begin(self):
        if not self.enabled:
            return
        self.path.unlink(missing_ok=True)
        self.path = self.data/'render-progress'/f'{self.uid}-{self.index}.stats'
        self.path.unlink(missing_ok=True)
        self.started, self.clock = time.time(), time.monotonic()
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO render_progress VALUES(?,?)',
                      (self.uid, json.dumps(dict(stages=self.items, index=self.index, started=self.started))))

    def finish(self):
        if not self.enabled:
            return
        item = self.items[self.index]
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO render_steps VALUES(?,?,?,?,?,?)',
                      (self.uid, self.index, item['kind'], profile(self.plan), item['units'], max(.001, time.monotonic()-self.clock)))
        self.index += 1
        self.begin()

    def run(self, args, timeout=1800):
        if not self.enabled:
            return self.execute(args, timeout)
        args = [args[0], '-progress', str(self.path), '-stats_period', '1', *args[1:]]
        result = self.execute(args, timeout)
        self.finish()
        return result

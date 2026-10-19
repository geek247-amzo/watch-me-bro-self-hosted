"""Project-owned creative assets and explicit, non-replayed paid generation."""
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import local_ai

SCHEMA = '''
CREATE TABLE IF NOT EXISTS creative_routes(
 feature TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
 reserve_usd REAL NOT NULL, updated REAL NOT NULL, input_rate REAL NOT NULL, output_rate REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, project TEXT REFERENCES projects(id), name TEXT, kind TEXT,
 mime TEXT, sha256 TEXT, bytes INTEGER, width INTEGER, height INTEGER,
 duration REAL, alpha INTEGER, provenance TEXT, created REAL);
CREATE TABLE IF NOT EXISTS creative_jobs(
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE, project TEXT REFERENCES projects(id),
 state TEXT, spec TEXT, asset TEXT, error TEXT, created REAL, finished REAL);
'''
FEATURES = {'artwork': ['openai', 'google'], 'music': ['google'],
            'titles': ['openai', 'google', 'anthropic', 'lmstudio'], 'analysis': ['openai', 'google', 'anthropic', 'lmstudio']}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def request_json(url, key, payload, provider, limit=32*1024**2):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    headers.update({'Authorization': 'Bearer '+key} if provider == 'openai' else
                   {'x-goog-api-key': key} if provider == 'google' else
                   {'x-api-key': key, 'anthropic-version': '2023-06-01'})
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(req, timeout=240) as response:
            raw = response.read(limit+1)
        if len(raw) > limit:
            raise ValueError('Provider response exceeded the safe size limit. No automatic retry was made.')
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'AI request returned HTTP {exc.code}. Check model access and provider limits. Its estimate remains reserved; no automatic retry was made.') from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('AI response was unavailable. Its estimate remains reserved; no automatic retry was made.') from None


def model_supported(feature, provider, model):
    if provider not in FEATURES.get(feature, []):
        return False
    if provider == 'lmstudio':
        return isinstance(model,str) and 1<=len(model)<=180 and not any(ord(ch)<32 for ch in model)
    if feature == 'music':
        return model == 'lyria-3-clip-preview'
    if feature == 'artwork':
        return (provider == 'openai' and bool(re.fullmatch(r'gpt-image-(?:1(?:\.5)?|2(?:\.5-(?:sunburst|flare))?)(?:-\d{4}-\d{2}-\d{2})?', model))) or (provider == 'google' and model.startswith('gemini-') and ('image' in model or 'nano-banana' in model))
    return (provider == 'openai' and bool(re.match(r'gpt-(?:4o|4\.1|5)', model)) and 'image' not in model) or (provider == 'google' and model.startswith('gemini-') and not any(s in model for s in ['image', 'banana', 'tts', 'embedding'])) or (provider == 'anthropic' and model.startswith('claude-'))


def generate(spec, key, references):
    provider, model, kind = spec['provider'], spec['model'], spec['feature']
    prompt = spec['prompt']
    refs = [base64.b64encode(p.read_bytes()).decode() for p in references]
    if kind == 'artwork' and provider == 'openai':
        payload = dict(model=model, prompt=prompt, n=1, size=spec['size'], quality='medium',
                       background='transparent' if spec['transparent'] else 'opaque', output_format='png')
        if refs:
            payload['images'] = [{'image_url': 'data:image/png;base64,'+ref} for ref in refs]
        result = request_json('https://api.openai.com/v1/images/'+('edits' if refs else 'generations'), key, payload, provider)
        return base64.b64decode(result['data'][0]['b64_json'], validate=True), 'image'
    if kind == 'artwork':
        if 'nano-banana' in model:
            parts = [{'type': 'text', 'text': prompt}] + [{'type': 'image', 'mime_type': 'image/png', 'data': ref} for ref in refs]
            ratio = {'1536x1024': '3:2', '1024x1536': '2:3', '1024x1024': '1:1'}[spec['size']]
            result = request_json('https://generativelanguage.googleapis.com/v1beta/interactions', key,
                                  {'model': model, 'input': parts, 'response_format': {'type': 'image', 'mime_type': 'image/png', 'aspect_ratio': ratio, 'image_size': '1K'}}, provider)
            for step in result.get('steps', []):
                if step.get('type') == 'model_output':
                    for block in step.get('content', []):
                        if block.get('type') == 'image':
                            return base64.b64decode(block['data'], validate=True), 'image'
            raise ValueError('The provider returned no picture. No automatic retry was made.')
        parts = [{'text': prompt}] + [{'inline_data': {'mime_type': 'image/png', 'data': ref}} for ref in refs]
        result = request_json('https://generativelanguage.googleapis.com/v1beta/models/'+urllib.parse.quote(model, safe='-_.')+':generateContent', key,
                              {'contents': [{'parts': parts}], 'generationConfig': {'responseModalities': ['TEXT', 'IMAGE']}}, provider)
        for part in result['candidates'][0]['content']['parts']:
            inline = part.get('inlineData', part.get('inline_data', {}))
            if inline.get('mimeType', inline.get('mime_type')) in ['image/png', 'image/jpeg']:
                return base64.b64decode(inline['data'], validate=True), 'image'
        raise ValueError('The provider returned no picture. Review its safety/model settings before trying again.')
    if kind == 'music':
        result = request_json('https://generativelanguage.googleapis.com/v1beta/interactions', key,
                              {'model': model, 'input': 'Create a 30-second instrumental background music clip. No vocals. '+prompt}, provider)
        for step in result.get('steps', []):
            if step.get('type') == 'model_output':
                for block in step.get('content', []):
                    if block.get('type') == 'audio':
                        return base64.b64decode(block['data'], validate=True), 'audio'
        raise ValueError('The provider returned no music. No automatic retry was made.')
    raise ValueError('Unsupported creative operation.')


def vision_request(provider, key, model, prompt, frames, local_endpoint=None):
    """Non-OpenAI visual adapters; normalise usage into the existing scan ledger."""
    if provider == 'lmstudio':
        return local_ai.chat(local_endpoint,key,model,prompt,6000,frames)
    if provider == 'anthropic':
        content = []
        for stamp, path in frames:
            content += [{'type': 'text', 'text': f'SOURCE TIMESTAMP {stamp}'},
                        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(path.read_bytes()).decode()}}]
        content.append({'type': 'text', 'text': 'Return only valid JSON, without Markdown. '+prompt})
        data = request_json('https://api.anthropic.com/v1/messages', key,
                            {'model': model, 'max_tokens': 6000, 'messages': [{'role': 'user', 'content': content}]}, provider, 256*1024)
        if data.get('stop_reason') != 'end_turn':
            raise ValueError('The model did not finish its response. No automatic paid retry was made.')
        output = ''.join(p.get('text', '') for p in data['content'] if p.get('type') == 'text')
        usage = data.get('usage', {})
        return output, {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')}
    parts = []
    for stamp, path in frames:
        parts += [{'text': f'SOURCE TIMESTAMP {stamp}'}, {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(path.read_bytes()).decode()}}]
    parts.append({'text': prompt})
    data = request_json('https://generativelanguage.googleapis.com/v1beta/models/'+urllib.parse.quote(model, safe='-_.')+':generateContent', key,
                        {'contents': [{'parts': parts}], 'generationConfig': {'maxOutputTokens': 6000, 'responseMimeType': 'application/json'}}, provider, 256*1024)
    choice = data['candidates'][0]
    if choice.get('finishReason') != 'STOP':
        raise ValueError('The model did not finish its response. No automatic paid retry was made.')
    usage = data.get('usageMetadata', {})
    return ''.join(p.get('text', '') for p in choice['content']['parts']), {'prompt_tokens': usage.get('promptTokenCount'), 'completion_tokens': (usage.get('candidatesTokenCount', 0)+usage.get('thoughtsTokenCount', 0)) if 'candidatesTokenCount' in usage else None}


class CreativeEngine:
    def __init__(self, db, media, run, decrypt, audit):
        self.db, self._media, self.run, self.decrypt, self.audit = db, media, run, decrypt, audit

    @property
    def media(self):
        return self._media()

    def initialize(self):
        (self.media/'assets').mkdir(exist_ok=True)
        with self.db() as c:
            c.executescript(SCHEMA)
            c.execute("UPDATE creative_jobs SET state='interrupted',error='Service restarted during generation. Estimate remains reserved; no automatic retry.',finished=? WHERE state='running'", (time.time(),))

    def settings(self):
        with self.db() as c:
            local_config=c.execute('SELECT base_url,updated FROM lmstudio_settings WHERE id=1').fetchone()
            return {'features': FEATURES, 'routes': [dict(r) for r in c.execute('SELECT * FROM creative_routes')],
                    'localModels':[dict(r) for r in c.execute('SELECT * FROM lmstudio_models')],
                    'localSettings':dict(local_config) if local_config else None,
                    'models': [dict(r) for r in c.execute('SELECT provider,model FROM provider_models')]}

    def save_route(self, body):
        feature, provider, model = body.get('feature'), body.get('provider'), body.get('model')
        cost = body.get('reserveUsd')
        rates = [body.get('inputRate'), body.get('outputRate')]
        if provider == 'lmstudio':
            cost,rates=0,[0,0]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10000 or (provider != 'lmstudio' and v == 0) for v in rates):
            raise ValueError('Enter this assigned model’s input/output token prices. Artwork/music use the flat request reserve instead.')
        if not isinstance(model, str) or not model_supported(feature, provider, model):
            raise ValueError('Choose a model that supports this job. Anthropic does not generate pictures or music.')
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or not 0 <= cost <= 20 or (provider != 'lmstudio' and cost == 0):
            raise ValueError('Enter a conservative per-generation reserve between $0 and $20.')
        with self.db() as c:
            if provider == 'lmstudio' and feature == 'analysis':
                capability=c.execute('SELECT vision FROM lmstudio_models WHERE model=?',(model,)).fetchone()
                if not capability or not capability['vision']:
                    raise ValueError('Visual analysis requires a vision-capable model reported by LM Studio. Refresh its catalogue or update LM Studio; text-only/unknown models can still write titles.')
            if not c.execute('SELECT 1 FROM provider_models WHERE provider=? AND model=?', (provider, model)).fetchone():
                raise ValueError('Verify this model in the provider catalogue first. Model access is not proven until a confirmed request succeeds.')
            if not c.execute('SELECT 1 FROM provider_budgets WHERE provider=?', (provider,)).fetchone():
                raise ValueError('Save this provider’s monthly cap and token prices first.')
            c.execute('INSERT INTO creative_routes VALUES(?,?,?,?,?,?,?) ON CONFLICT(feature) DO UPDATE SET provider=excluded.provider,model=excluded.model,reserve_usd=excluded.reserve_usd,updated=excluded.updated,input_rate=excluded.input_rate,output_rate=excluded.output_rate', (feature, provider, model, cost, time.time(), *rates))
            self.audit(c, 'creative.route-saved', feature)
        return {'ok': True}

    def store(self, project, raw, kind, name, provenance):
        if kind not in ['image', 'audio'] or not 0 < len(raw) <= (10 if kind == 'image' else 25)*1024**2:
            raise ValueError('Use a PNG/JPEG up to 10 MB, or MP3/WAV/M4A up to 25 MB.')
        with self.db() as c:
            if not c.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Choose an existing project.')
        if shutil.disk_usage(self.media).free < 2*1024**3+len(raw)*4 or sum(p.stat().st_size for p in self.media.rglob('*') if p.is_file())+len(raw)*4 > 40*1024**3:
            raise ValueError('Not enough media space for this asset.')
        uid = secrets.token_hex(16)
        scratch, target = self.media/'assets'/(uid+'.upload'), self.media/'assets'/uid
        scratch.write_bytes(raw)
        try:
            formats = 'png_pipe,jpeg_pipe' if kind == 'image' else 'mp3,wav,mov'
            meta = json.loads(self.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats,
                                        '-show_format', '-show_streams', '-of', 'json', str(scratch)], 30))
            streams = meta['streams']
            width = height = alpha = 0
            duration = 0
            if kind == 'image':
                video = next(s for s in streams if s['codec_type'] == 'video')
                width, height = video['width'], video['height']
                if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width*height > 16*1024**2:
                    raise ValueError('Picture dimensions exceed the safe 16-megapixel limit.')
                alpha = int(video.get('pix_fmt') in ['rgba', 'bgra', 'argb', 'abgr', 'yuva420p', 'ya8', 'pal8'])
                vf = 'scale=1536:1536:force_original_aspect_ratio=decrease:force_divisible_by=2,format=rgba'
                self.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1', '-filter_threads', '1', '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats, '-i', str(scratch), '-vf', vf,
                          '-frames:v', '1', '-threads', '1', '-f', 'image2', '-c:v', 'png', str(target)], 60)
                mime = 'image/png'
            else:
                if any(s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic') for s in streams) or not any(s['codec_type'] == 'audio' for s in streams):
                    raise ValueError('Upload an audio-only music file.')
                duration = float(meta['format']['duration'])
                if not math.isfinite(duration) or not 0 < duration <= 1800:
                    raise ValueError('Music must be no longer than 30 minutes.')
                self.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats, '-i', str(scratch), '-map', '0:a:0', '-vn', '-c:a', 'libmp3lame', '-ar', '48000', '-ac', '2', '-f', 'mp3', str(target)], 120)
                mime = 'audio/mpeg'
            provenance = {**provenance, 'inputSha256': hashlib.sha256(raw).hexdigest(), 'licence': 'Owner must review permission and provider terms before sharing.'}
            with target.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            with self.db() as c:
                c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (uid, project, str(name)[:160], kind, mime, digest, target.stat().st_size, width, height, duration, alpha, json.dumps(provenance), time.time()))
                self.audit(c, 'asset.created', uid)
            return {'id': uid}
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            scratch.unlink(missing_ok=True)

    def quote(self, body):
        feature, project = body.get('feature'), body.get('project')
        prompt = body.get('prompt')
        refs = body.get('references', [])
        if feature not in ['artwork', 'music'] or not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000 or not isinstance(refs, list) or len(refs) > 3 or any(not isinstance(uid, str) for uid in refs) or len(set(refs)) != len(refs):
            raise ValueError('Choose artwork or music, describe it, and select up to three reference pictures.')
        with self.db() as c:
            route = c.execute('SELECT * FROM creative_routes WHERE feature=?', (feature,)).fetchone()
            if not route or not c.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Choose a project and assign this AI job in Settings first.')
            provider, model = route['provider'], route['model']
            key = c.execute('SELECT updated FROM provider_credentials WHERE provider=?', (provider,)).fetchone()
            budget = c.execute('SELECT * FROM provider_budgets WHERE provider=?', (provider,)).fetchone()
            if not key or not budget or not c.execute('SELECT 1 FROM provider_models WHERE provider=? AND model=?', (provider, model)).fetchone():
                raise ValueError('Verify the assigned provider key, catalogue and monthly limit in Settings.')
            references = []
            for uid in refs:
                asset = c.execute("SELECT id,sha256 FROM assets WHERE id=? AND project=? AND kind='image'", (uid, project)).fetchone()
                if not asset:
                    raise ValueError('Reference pictures must belong to this project.')
                references.append(dict(asset))
            month = time.strftime('%Y-%m', time.gmtime())
            usage = c.execute('SELECT * FROM provider_usage WHERE provider=? AND month=?', (provider, month)).fetchone()
        if feature == 'music' and refs:
            raise ValueError('Music generation currently uses your description only. Do not select pictures for music.')
        transparent = body.get('transparent') is True
        if transparent and (feature != 'artwork' or provider != 'openai'):
            raise ValueError('Transparent generation requires an OpenAI GPT Image artwork route. Gemini artwork is offered as opaque only.')
        size = body.get('size', '1536x1024')
        if size not in ['1536x1024', '1024x1536', '1024x1024']:
            raise ValueError('Choose a supported picture shape.')
        spec = dict(feature=feature, project=project, provider=provider, model=model, prompt=prompt.strip(), references=references, transparent=transparent, size=size,
                    reserveUsd=route['reserve_usd'], routeUpdated=route['updated'], keyUpdated=key['updated'], budgetUpdated=budget['updated'], cap=budget['monthly_cap_usd'], month=month)
        quote = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        remaining = spec['cap'] - (usage['spent_usd']+usage['reserved_usd'] if usage else 0)
        return dict(quote=quote, spec=spec, remainingUsd=max(0, remaining), affordable=spec['reserveUsd'] <= remaining,
                    disclosure='Your description'+(' and selected reference pictures' if refs else '')+' will be sent to '+provider+'. Provider account terms govern retention and rights. This is a paid request. The owner-entered reserve is a local estimate, not a provider billing ceiling. On success this estimate is recorded as estimated usage; on an ambiguous failure it stays reserved. Review the result before using it.')

    def enqueue(self, body):
        request_id = body.get('requestId', '')
        if not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9-]{16,80}', request_id):
            raise ValueError('A unique generation request ID is required.')
        with self.db() as c:
            old = c.execute('SELECT id FROM creative_jobs WHERE request_id=?', (request_id,)).fetchone()
            if old:
                return {'id': old['id']}
        quoted = self.quote(body)
        if body.get('consent') is not True or body.get('quote') != quoted['quote']:
            raise ValueError('Review and explicitly confirm a current generation quote first.')
        spec, uid = quoted['spec'], secrets.token_hex(16)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT id FROM creative_jobs WHERE request_id=?', (request_id,)).fetchone()
            if old:
                return {'id': old['id']}
            if c.execute("SELECT count(*) FROM creative_jobs WHERE state IN ('queued','running')").fetchone()[0] >= 3:
                raise ValueError('Three creative requests are already waiting. Let them finish first.')
            self.check_settings(c, spec)
            c.execute('INSERT OR IGNORE INTO provider_usage VALUES(?,?,0,0,0)', (spec['provider'], spec['month']))
            usage = c.execute('SELECT * FROM provider_usage WHERE provider=? AND month=?', (spec['provider'], spec['month'])).fetchone()
            if usage['spent_usd']+usage['reserved_usd']+spec['reserveUsd'] > spec['cap']:
                raise ValueError('This request would exceed the local monthly budget.')
            c.execute('UPDATE provider_usage SET reserved_usd=reserved_usd+? WHERE provider=? AND month=?', (spec['reserveUsd'], spec['provider'], spec['month']))
            c.execute('INSERT INTO creative_jobs(id,request_id,project,state,spec,created) VALUES(?,?,?,?,?,?)', (uid, request_id, spec['project'], 'queued', json.dumps(spec), time.time()))
            self.audit(c, 'creative.queued', uid)
        return {'id': uid}

    def check_settings(self, c, spec):
        route = c.execute('SELECT updated FROM creative_routes WHERE feature=?', (spec['feature'],)).fetchone()
        key = c.execute('SELECT * FROM provider_credentials WHERE provider=?', (spec['provider'],)).fetchone()
        budget = c.execute('SELECT updated FROM provider_budgets WHERE provider=?', (spec['provider'],)).fetchone()
        if not route or not key or not budget or route['updated'] != spec['routeUpdated'] or key['updated'] != spec['keyUpdated'] or budget['updated'] != spec['budgetUpdated'] or time.strftime('%Y-%m', time.gmtime()) != spec['month']:
            raise ValueError('AI settings or billing month changed. Review a new quote; no request was sent.')
        usage = c.execute('SELECT spent_usd,reserved_usd FROM provider_usage WHERE provider=? AND month=?', (spec['provider'], spec['month'])).fetchone()
        if usage and usage['spent_usd']+usage['reserved_usd'] > spec['cap']+1e-9:
            raise ValueError('The local provider budget is exhausted. No request was sent.')
        return key

    def tick(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM creative_jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            spec = json.loads(row['spec'])
            c.execute("UPDATE creative_jobs SET state='running' WHERE id=?", (row['id'],))
        sent = False
        try:
            with self.db() as c:
                credential = self.check_settings(c, spec)
            paths = [self.media/'assets'/r['id'] for r in spec['references']]
            for ref, path in zip(spec['references'], paths):
                with path.open('rb') as f:
                    if hashlib.file_digest(f, 'sha256').hexdigest() != ref['sha256']:
                        raise ValueError('A reference picture changed. Restore it before generation.')
            key = self.decrypt(spec['provider'], credential['nonce'], credential['ciphertext'])
            with self.db() as c:
                c.execute('UPDATE provider_usage SET requests=requests+1 WHERE provider=? AND month=?', (spec['provider'], spec['month']))
            sent = True
            raw, kind = generate(spec, key, paths)
            asset = self.store(spec['project'], raw, kind, ('AI picture' if kind == 'image' else 'AI music'),
                               {'origin': 'generated', 'provider': spec['provider'], 'model': spec['model'], 'prompt': spec['prompt'], 'references': spec['references'], 'requestedTransparent': spec['transparent'], 'estimatedCostUsd': spec['reserveUsd']})
            with self.db() as c:
                c.execute('UPDATE provider_usage SET reserved_usd=MAX(0,reserved_usd-?),spent_usd=spent_usd+? WHERE provider=? AND month=?', (spec['reserveUsd'], spec['reserveUsd'], spec['provider'], spec['month']))
                c.execute("UPDATE creative_jobs SET state='complete',asset=?,finished=? WHERE id=?", (asset['id'], time.time(), row['id']))
                self.audit(c, 'creative.complete', row['id'])
        except Exception as exc:
            with self.db() as c:
                if not sent:
                    c.execute('UPDATE provider_usage SET reserved_usd=MAX(0,reserved_usd-?) WHERE provider=? AND month=?', (spec['reserveUsd'], spec['provider'], spec['month']))
                error = str(exc)[:300] if isinstance(exc, ValueError) else 'Generation could not finish. Review model access and media format. No automatic retry was made.'
                c.execute("UPDATE creative_jobs SET state='failed',error=?,finished=? WHERE id=?", (error, time.time(), row['id']))
                self.audit(c, 'creative.failed', row['id'])
        return True


def validate_design(body, assets):
    design = body.get('design', {})
    if not isinstance(design, dict):
        raise ValueError('Artwork and music settings must be an object.')
    result = {}
    for slot in ['intro', 'outro', 'overlay', 'music']:
        uid = design.get(slot) or ''
        if uid and (not isinstance(uid, str) or uid not in assets or assets[uid]['kind'] != ('audio' if slot == 'music' else 'image')):
            raise ValueError('Choose pictures and music from this project’s library.')
        result[slot] = uid
    for name, default, low, high in [('music_volume', .15, 0, 1), ('overlay_size', .25, .1, .6)]:
        value = design.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Choose valid music volume and picture size.')
        result[name] = value
    result['position'] = design.get('position', 'bottom-right')
    result['music_scope'] = design.get('music_scope', 'all')
    if result['position'] not in ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'centre'] or result['music_scope'] not in ['all', 'cards', 'gameplay']:
        raise ValueError('Choose a valid picture position and music placement.')
    return result


def composite(run, media, folder, video, design, width, height, intro, gameplay, outro):
    """Alpha-aware card backgrounds and gameplay overlays; music mixed on final timeline."""
    if not any(design.get(k) for k in ['intro', 'outro', 'overlay', 'music']):
        return
    total = intro+gameplay+outro
    args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1', '-filter_complex_threads', '1', '-i', str(video)]
    graph, current, index = [], '0:v', 1
    for slot in ['intro', 'outro', 'overlay']:
        if not design.get(slot):
            continue
        args += ['-loop', '1', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'png_pipe', '-i', str(media/'assets'/design[slot])]
        label = f'pic{index}'
        size = max(2, int(width*design['overlay_size'])//2*2) if slot == 'overlay' else width
        graph.append(f'[{index}:v]scale={size}:{height}:force_original_aspect_ratio=decrease,format=rgba,setsar=1[{label}]')
        if slot == 'intro':
            enable, x, y = f'between(t,0,{max(0,intro-.001)})', '(W-w)/2', '(H-h)/2'
        elif slot == 'outro':
            enable, x, y = f'gte(t,{intro+gameplay})', '(W-w)/2', '(H-h)/2'
        else:
            position = design['position']
            x = '(W-w)/2' if position == 'centre' else ('W-w-20' if 'right' in position else '20')
            y = '(H-h)/2' if position == 'centre' else ('H-h-20' if 'bottom' in position else '20')
            enable = f'between(t,{intro},{intro+gameplay-.001})'
        out = f'v{index}'
        graph.append(f"[{current}][{label}]overlay=x={x}:y={y}:enable='{enable}':eof_action=repeat:shortest=1[{out}]")
        current, index = out, index+1
        # One measured title layer is composited after all artwork; never redraw here.
    audio = '0:a'
    if design.get('music'):
        args += ['-stream_loop', '-1', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mp3', '-i', str(media/'assets'/design['music'])]
        scope = design['music_scope']
        volume = str(design['music_volume'])
        if scope != 'all':
            condition = f'between(t,{intro},{intro+gameplay})'
            volume = f"{volume}*{'not('+condition+')' if scope == 'cards' else condition}"
        fade = min(1, total/3)
        graph.append(f"[{index}:a]atrim=duration={total},asetpts=PTS-STARTPTS,volume='{volume}':eval=frame,afade=t=in:d={fade},afade=t=out:st={max(0,total-fade)}:d={fade}[music]")
        graph.append('[0:a][music]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]')
        audio = 'mix'
    args += ['-filter_complex', ';'.join(graph), '-map', f'[{current}]' if current != '0:v' else current,
             '-map', '[mix]' if audio == 'mix' else audio, '-t', str(total), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', '-threads', '1', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(folder/'styled.mp4')]
    run(args)
    (folder/'styled.mp4').replace(video)

"""Consistent SQLite backup plus copies of immutable, completed media. No deletion."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import os

os.umask(0o077)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
private = Path(os.environ.get('WMB_PRIVATE_DIR', '/opt/watch-me-bro/private'))
media = Path(os.environ.get('WMB_MEDIA_ROOT', '/opt/watch-me-bro/media'))
output = Path(os.environ.get('WMB_BACKUP_ROOT', '/opt/watch-me-bro/backups')) / stamp
media_backup = Path(os.environ.get('WMB_MEDIA_BACKUP_ROOT', '/opt/watch-me-bro/media-backups'))
if not media.is_dir() or not private.joinpath('data/studio.sqlite').is_file():
    raise SystemExit('Studio state/media is unavailable; refusing an incomplete backup.')
if shutil.disk_usage(output.parent.parent).free < 2*1024**3:
    raise SystemExit('System disk reserve reached.')
output.mkdir(parents=True, mode=0o700)
media_backup.mkdir(parents=True, exist_ok=True, mode=0o700)
with sqlite3.connect(f'file:{private}/data/studio.sqlite?mode=ro', uri=True) as source, sqlite3.connect(output / 'studio.sqlite') as copy:
    source.backup(copy)
    if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('SQLite restore validation failed.')
    expected = [('sources/' + row[0]) for row in copy.execute('SELECT id FROM sources')]
    for (uid,) in copy.execute("SELECT id FROM jobs WHERE state IN ('review','approved')"):
        expected += [f'exports/{uid}/{name}' for name in ['video.mp4', 'manifest.json', 'captions.srt', 'thumbnail.jpg']]
    if copy.execute("SELECT 1 FROM sqlite_master WHERE name='assets'").fetchone():
        expected += ['assets/' + row[0] for row in copy.execute('SELECT id FROM assets')]
manifest = {'created': stamp, 'database': 'integrity_check passed', 'media': [], 'warning': 'Media copy is on the same physical disk. Off-server backup is still required.'}
for relative in expected:
    src, dst = media / relative, media_backup / relative
    if not src.is_file():
        raise SystemExit('A referenced media file is missing. Backup is incomplete.')
    if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
        if shutil.disk_usage(media_backup).free-src.stat().st_size < 2*1024**3:
            raise SystemExit('Media backup reserve reached.')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    def sha(path):
        with path.open('rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else slow_sha(f)
    def slow_sha(f):
        digest = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024*1024), b''):
            digest.update(chunk)
        return digest.hexdigest()
    original, saved = sha(src), sha(dst)
    if original != saved:
        raise SystemExit('Media checksum mismatch; backup is incomplete.')
    manifest['media'].append({'path': relative, 'bytes': src.stat().st_size, 'sha256': saved})
shutil.copy2(private / 'admin-password', output / 'admin-password')
shutil.copy2(private / 'credential-encryption-key', output / 'credential-encryption-key')
shutil.copy2(Path(__file__).parent / 'compose.yml', output / 'compose.yml')
manifest['state'] = 'COMPLETE'
(output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'state': 'COMPLETE', 'path': str(output), 'mediaFiles': len(expected), 'database': 'integrity_check passed'}))

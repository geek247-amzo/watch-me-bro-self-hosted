"""Operator-only clean retest. Archive, never erase; preserve keys and spending.

Stop ONLY WMB and cancel/wait for all work first. No web reset endpoint exists.
"""
import argparse
from contextlib import closing
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

CONTENT = ('reviews', 'jobs', 'plans', 'analyses', 'creative_jobs', 'assets', 'sources', 'projects', 'audit')
KEEP = ('provider_credentials', 'provider_models', 'provider_budgets', 'provider_usage',
        'creative_routes', 'lmstudio_settings', 'lmstudio_models')


def fingerprint(conn):
    return {table: hashlib.sha256(repr(conn.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()).encode()).hexdigest()
            for table in KEEP}


def reset_workspace(data, media, state_archive, media_archive):
    paths = [Path(p) for p in (data, media, state_archive, media_archive)]
    data, media, state_archive, media_archive = paths
    if any(not p.is_absolute() or p.is_symlink() for p in paths) or len(set(paths)) != 4:
        raise ValueError('Use distinct absolute non-symlink paths.')
    if any(a in b.parents for a in paths for b in paths if a != b):
        raise ValueError('Live/archive paths must not nest.')
    if not (data / 'studio.sqlite').is_file() or not media.is_dir():
        raise ValueError('Existing state and media are required.')
    if state_archive.exists() or media_archive.exists():
        raise ValueError('Archive already exists; refusing overwrite.')
    # Validate everything before moving anything; include every media fragment.
    with closing(sqlite3.connect(f'file:{data}/studio.sqlite?mode=ro', uri=True)) as source:
        for table in ('jobs', 'analyses', 'creative_jobs'):
            if source.execute(f"SELECT count(*) FROM {table} WHERE state IN ('queued','running')").fetchone()[0]:
                raise ValueError('Cancel/wait for active work before resetting.')
        preserved = fingerprint(source)
        counts = {t: source.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in CONTENT}
        prepared = Path(tempfile.mkdtemp(prefix='.wmb-reset-', dir=data.parent))
        try:
            with closing(sqlite3.connect(prepared / 'studio.sqlite')) as fresh:
                source.backup(fresh)
                fresh.execute('PRAGMA foreign_keys=ON')
                for table in CONTENT:
                    fresh.execute(f'DELETE FROM {table}')
                fresh.execute('INSERT INTO audit(action,object,created) VALUES(?,?,?)',
                              ('workspace.reset', 'archived-for-clean-retest', time.time()))
                fresh.commit()
                if fresh.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or fresh.execute('PRAGMA foreign_key_check').fetchall() or fingerprint(fresh) != preserved:
                    raise RuntimeError('Fresh database verification failed.')
            shutil.copystat(data, prepared)
            shutil.copystat(data / 'studio.sqlite', prepared / 'studio.sqlite')
            manifest = {'state': 'PREPARED', 'cleared': counts, 'settingsAndUsagePreserved': True,
                        'dataArchive': str(state_archive), 'mediaArchive': str(media_archive), 'files': []}
            for path in sorted(media.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Unexpected media symlink; manual review required.')
                if path.is_file():
                    with path.open('rb') as f:
                        digest = hashlib.file_digest(f, 'sha256').hexdigest()
                    manifest['files'].append({'path': str(path.relative_to(media)), 'bytes': path.stat().st_size, 'sha256': digest})
            data.rename(state_archive)
            try:
                media.rename(media_archive)
                try:
                    media.mkdir(mode=0o700)
                    shutil.copystat(media_archive, media)
                    prepared.rename(data)
                except BaseException:
                    if media.exists():
                        media.rmdir()  # Newly created empty root ONLY.
                    media_archive.rename(media)
                    raise
            except BaseException:
                state_archive.rename(data)
                raise
            manifest['state'] = 'COMPLETE'
            (state_archive / 'reset-manifest.json').write_text(json.dumps(manifest, indent=2))
            (state_archive / 'reset-manifest.json').chmod(0o600)
            return {k: v for k, v in manifest.items() if k != 'files'} | {'archivedFiles': len(manifest['files'])}
        finally:
            if prepared.exists():
                # Only our exact temporary staging directory, never live/archive state.
                shutil.rmtree(prepared)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    container = os.environ.get('WMB_CONTAINER_NAME', 'watch-me-bro')
    state = subprocess.check_output(['docker', 'inspect', '--format', '{{.State.Status}}', container], text=True).strip()
    if state != 'exited':
        raise SystemExit(f'Stop only {container} first; it must be exited.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    private = Path(os.environ.get('WMB_PRIVATE_DIR', '/opt/watch-me-bro/private'))
    media = Path(os.environ.get('WMB_MEDIA_ROOT', '/opt/watch-me-bro/media'))
    media_backups = Path(os.environ.get('WMB_MEDIA_BACKUP_ROOT', '/opt/watch-me-bro/media-backups'))
    print(json.dumps(reset_workspace(private / 'data', media,
                                    private / ('reset-' + stamp),
                                    media_backups / ('reset-' + stamp))))

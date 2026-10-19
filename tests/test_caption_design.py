import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

import app
from captions import STYLES, subtitle_filter


class CaptionDesign(unittest.TestCase):
    def test_style_roundtrip_and_reject_filter_injection(self):
        plan = dict(format='landscape', audio='mute', cuts=[dict(source='s', start=0, end=2)])
        sources = {'s': dict(id='s', duration=3)}
        self.assertEqual(app.validate_plan(plan, sources)['caption_style'], 'studio')
        for style in STYLES:
            self.assertEqual(app.validate_plan(dict(plan, caption_style=style), sources)['caption_style'], style)
        for style in ['invalid', "studio,movie=/etc/passwd", None, {}, True]:
            with self.subTest(style=style), self.assertRaises(ValueError):
                app.validate_plan(dict(plan, caption_style=style), sources)

    def test_real_ffmpeg_all_caption_styles_and_shapes(self):
        with tempfile.TemporaryDirectory(prefix='wmb-caption-test-') as tmp:
            srt = Path(tmp) / 'captions.srt'
            srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nA great moment!\n')
            for size in ['320x180', '180x320']:
                for style in STYLES:
                    result = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-filter_threads', '1', '-f', 'lavfi', '-i', 'color=c=black:s='+size+':d=0.2', '-vf', subtitle_filter(srt, style), '-frames:v', '1', '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertGreater(sum(result.stdout), 0, 'Caption must render visible pixels')


class WorkspaceReset(unittest.TestCase):
    def test_reset_archives_media_clears_content_preserves_settings_and_usage(self):
        spec = importlib.util.spec_from_file_location('reset_workspace', Path(__file__).resolve().parents[1] / 'ops/reset-workspace.py')
        reset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reset)
        with tempfile.TemporaryDirectory(prefix='wmb-reset-test-') as tmp:
            root = Path(tmp)
            data, media, old_data, old_media = [root / p for p in ['data', 'media', 'old-data', 'old-media']]
            data.mkdir(); media.mkdir()
            (media / 'source').write_bytes(b'original untouched')
            with sqlite3.connect(data / 'studio.sqlite') as conn:
                for table in reset.KEEP:
                    conn.execute(f'CREATE TABLE {table}(id TEXT, value TEXT)')
                    conn.execute(f'INSERT INTO {table} VALUES(?,?)', ('setting', 'preserve'))
                for table in reset.CONTENT:
                    if table == 'audit':
                        conn.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,action TEXT,object TEXT,created REAL)')
                    else:
                        conn.execute(f'CREATE TABLE {table}(id TEXT, state TEXT)')
                        conn.execute(f'INSERT INTO {table} VALUES(?,?)', ('test', 'complete'))
            result = reset.reset_workspace(data, media, old_data, old_media)
            self.assertEqual(result['state'], 'COMPLETE')
            self.assertEqual(list(media.iterdir()), [])
            self.assertEqual((old_media / 'source').read_bytes(), b'original untouched')
            with sqlite3.connect(data / 'studio.sqlite') as conn:
                for table in reset.CONTENT[:-1]:
                    self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
                for table in reset.KEEP:
                    self.assertEqual(conn.execute(f'SELECT * FROM {table}').fetchall(), [('setting', 'preserve')])
            with self.assertRaises(ValueError):
                reset.reset_workspace(data, media, old_data, old_media)
            with sqlite3.connect(data / 'studio.sqlite') as conn:
                conn.execute("INSERT INTO jobs VALUES('pending','queued')")
            with self.assertRaisesRegex(ValueError, 'active work'):
                reset.reset_workspace(data, media, root / 'another-data', root / 'another-media')
            self.assertTrue(data.is_dir())
            self.assertFalse((root / 'another-data').exists())


if __name__ == '__main__':
    unittest.main()
